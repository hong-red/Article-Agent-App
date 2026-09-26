"""妙文 · 公众号文章生成器 —— App 托管版后端（多用户）。

在网页版基础上新增：注册/登录（邀请码）、会话 token、用户密钥加密存储、按用户隔离文章、数据导出。
"""
import json
import os
import re
import shutil
import time

from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import crypto
import db
import imagesearch
import llm
import markdown_html as mh
import wechat

app = FastAPI(title="妙文 App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

config.ensure_dirs()
db.init_db()

BASE_DIR = config.BASE_DIR
STATIC_DIR = os.path.join(BASE_DIR, "static")
DEFAULT_COVER = os.path.join(BASE_DIR, "default_cover.jpg")
IMAGES_DIR = config.IMAGES_DIR


def _seed_invite():
    """首次启动若无邀请码，自动生成一个默认码（打印到日志，管理员可见）。"""
    if not db.list_invite_codes():
        code = "SMART2026"
        db.add_invite_code(code, max_uses=200)
        print(f"[妙文] 已生成默认邀请码：{code}（可注册 200 个账号）")


_seed_invite()


# ---------------- 认证 ----------------
def current_user(authorization: str = Header(default="")):
    token = authorization[7:] if authorization.startswith("Bearer ") else authorization
    uid = db.get_user_id_by_token(token) if token else None
    if not uid:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return uid


def _user_settings(uid):
    u = db.get_user(uid)
    raw = u["settings_enc"] if u else ""
    if not raw:
        return {}
    try:
        return json.loads(crypto.decrypt(raw))
    except Exception:
        return {}


class RegisterReq(BaseModel):
    username: str
    password: str
    invite_code: str


class LoginReq(BaseModel):
    username: str
    password: str


@app.post("/api/auth/register")
def register(req: RegisterReq):
    username = (req.username or "").strip()
    password = req.password or ""
    code = (req.invite_code or "").strip()
    if not (2 <= len(username) <= 20):
        raise HTTPException(400, "用户名需 2~20 个字符")
    if len(password) < 6:
        raise HTTPException(400, "密码至少 6 位")
    if db.get_user_by_username(username):
        raise HTTPException(400, "用户名已存在")
    if not db.use_invite_code(code, username):
        raise HTTPException(400, "邀请码无效或已被使用")
    salt, h = crypto.hash_password(password)
    db.create_user(username, salt, h, invite_code=code)
    return {"ok": True, "msg": "注册成功，请登录"}


@app.post("/api/auth/login")
def login(req: LoginReq):
    u = db.get_user_by_username((req.username or "").strip())
    if not u or not crypto.verify_password(req.password or "", u["password_salt"], u["password_hash"]):
        raise HTTPException(400, "用户名或密码错误")
    token = db.create_session(u["id"])
    return {"token": token, "username": u["username"]}


@app.post("/api/auth/logout")
def logout(authorization: str = Header(default="")):
    token = authorization[7:] if authorization.startswith("Bearer ") else authorization
    if token:
        db.delete_session(token)
    return {"ok": True}


@app.get("/api/auth/me")
def me(uid: int = Depends(current_user)):
    u = db.get_user(uid)
    return {"id": u["id"], "username": u["username"], "created_at": u["created_at"]}


@app.get("/api/info")
def info():
    return {"name": "妙文", "free_until": config.FREE_UNTIL}


# ---------------- 设置（密钥加密存储） ----------------
@app.get("/api/settings")
def get_settings(uid: int = Depends(current_user)):
    s = _user_settings(uid)
    return {
        "deepseek_api_key_set": bool(s.get("deepseek_api_key")),
        "deepseek_model": s.get("deepseek_model", "deepseek-chat"),
        "deepseek_base_url": s.get("deepseek_base_url", "https://api.deepseek.com"),
        "wechat_appid": s.get("wechat_appid", ""),
        "wechat_appsecret_set": bool(s.get("wechat_appsecret")),
        "wechat_author": s.get("wechat_author", ""),
        "wechat_source_url": s.get("wechat_source_url", ""),
        "wechat_need_open_comment": int(s.get("wechat_need_open_comment", 0) or 0),
        "wechat_only_fans_can_comment": int(s.get("wechat_only_fans_can_comment", 0) or 0),
    }


@app.post("/api/settings")
def save_settings(body: dict, uid: int = Depends(current_user)):
    s = _user_settings(uid)
    for k in ["deepseek_model", "deepseek_base_url", "wechat_appid", "wechat_appsecret",
              "wechat_author", "wechat_source_url"]:
        if k in body:
            s[k] = body[k] or ""
    for k in ["wechat_need_open_comment", "wechat_only_fans_can_comment"]:
        if k in body:
            s[k] = int(body[k] or 0)
    # 空 key 不覆盖，避免误清空
    if body.get("deepseek_api_key"):
        s["deepseek_api_key"] = body["deepseek_api_key"]
    db.update_user_settings(uid, crypto.encrypt(json.dumps(s, ensure_ascii=False)))
    return {"ok": True}


# ---------------- 写作模板 / 主题 ----------------
TEMPLATES = {
    "general": {"name": "通用", "title": "", "content": "", "format": ""},
    "listicle": {
        "name": "干货清单型",
        "title": "标题突出「数字 + 实用价值」，如「5 个方法」「一篇讲透」，制造收藏欲。",
        "content": "用「总-分」结构：开头快速点出痛点/收益；主体用 ## 分点，每点一个小标题 + 说明 + 例子；结尾给行动建议。多用加粗和列表。",
        "format": "小标题带序号感，重点结论加粗，关键处用引用块强调。",
    },
    "hook": {
        "name": "悬念钩子型",
        "title": "标题制造强烈好奇心或反差，如「为什么…」「…的真相」。",
        "content": "开头 1~2 句抛悬念或反常识结论，正文层层揭晓，结尾收束点题。多用短句、留白。",
        "format": "开头悬念句单独成段或加粗，段落短、节奏快。",
    },
    "emotion": {
        "name": "情感共鸣型",
        "title": "标题带情绪和代入感，如「多少人…」「原来…」。",
        "content": "用真实感强的故事或场景开头，中间引发共鸣，结尾升华情绪并引导转发。",
        "format": "金句单独成段并加粗，营造情绪节奏。",
    },
    "opinion": {
        "name": "热点观点型",
        "title": "标题带鲜明观点或冲突，如「…才是最…」「别再说…了」。",
        "content": "开头亮出犀利观点，主体摆事实讲道理、分点论证，结尾给有力结论。",
        "format": "核心观点用引用块或加粗突出，金句醒目。",
    },
    "story": {
        "name": "故事叙事型",
        "title": "标题有故事感和画面感，如「那个…的人，后来…」。",
        "content": "以具体人物/事件的故事线展开，有起承转合，结尾回扣主题。",
        "format": "段落自然连贯，关键转折可加粗。",
    },
}


@app.get("/api/themes")
def themes():
    return mh.list_schemes()


@app.get("/api/templates")
def templates():
    return [{"key": k, "name": v["name"]} for k, v in TEMPLATES.items()]


# ---------------- 生成 ----------------
class TitleReq(BaseModel):
    topic: str
    count: int = 5
    style: str = ""
    extra: str = ""
    template: str = "general"


class ContentReq(BaseModel):
    topic: str
    title: str
    style: str = ""
    extra: str = ""
    feedback: str = ""
    previous_content: str = ""
    template: str = "general"
    material_ids: list = []
    material_note: str = ""


class FormatReq(BaseModel):
    content: str
    title: str = ""
    theme: str = "default"
    tone: str = ""
    add_summary: bool = False
    add_golden: bool = False
    add_follow: bool = False
    polish: bool = True
    template: str = "general"
    images: list = []


class RenderReq(BaseModel):
    content: str
    title: str = ""
    theme: str = "default"


def _llm_for(uid, messages, temperature=0.8, max_tokens=4096):
    s = _user_settings(uid)
    return llm.chat(
        messages,
        s.get("deepseek_api_key", ""),
        model=s.get("deepseek_model", "deepseek-chat"),
        base_url=s.get("deepseek_base_url", "https://api.deepseek.com"),
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _read_material_text(uid, material_id, limit=8000):
    """读取素材文本内容供 AI 引用（txt/md/docx/pdf）；图片/压缩包返回 None。"""
    try:
        mid = int(material_id)
    except (TypeError, ValueError):
        return None
    m = db.get_material(uid, mid)
    if not m or not m.get("path") or not os.path.exists(m["path"]):
        return None
    p = m["path"]
    ext = os.path.splitext(p)[1].lower()
    name = m.get("name") or os.path.basename(p)
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".zip", ".rar", ".7z"):
        return None
    text = None
    try:
        if ext == ".docx":
            import docx
            d = docx.Document(p)
            text = "\n".join(para.text for para in d.paragraphs if para.text.strip())
        elif ext == ".pdf":
            import pdfplumber
            parts = []
            with pdfplumber.open(p) as pdf:
                for page in pdf.pages:
                    t = page.extract_text() or ""
                    if t.strip():
                        parts.append(t)
            text = "\n".join(parts)
        else:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
    except Exception:
        return None
    if not text or not text.strip():
        return None
    return f"【素材《{name}》】\n{text.strip()[:limit]}"


@app.post("/api/generate/titles")
def generate_titles(req: TitleReq, uid: int = Depends(current_user)):
    style_line = f"风格倾向：{req.style}" if req.style else ""
    extra_line = f"补充说明：{req.extra}" if req.extra else ""
    tpl = TEMPLATES.get(req.template, TEMPLATES["general"])
    tpl_line = f"标题风格：{tpl['title']}" if tpl["title"] else ""
    user = (
        f"请为主题「{req.topic}」生成 {req.count} 个吸引人的公众号文章标题。\n"
        "要求：1. 有吸引力，包含悬念、利益点或情绪点 2. 口语化但不低俗 3. 每个 15~25 字 "
        "4. 只输出标题，每行一个，不要编号、引号或解释\n"
        + (style_line + "\n" if style_line else "")
        + (extra_line + "\n" if extra_line else "")
        + (tpl_line + "\n" if tpl_line else "")
    )
    raw = _llm_for(
        uid,
        [{"role": "system", "content": "你是资深公众号主编，擅长起标题。"},
         {"role": "user", "content": user}],
        temperature=1.0, max_tokens=800,
    )
    titles = []
    for line in raw.split("\n"):
        t = re.sub(r'^[\d\-\*\.、\)）\s]+', '', line.strip()).strip().strip('「」""\'\'“”')
        if t and t not in titles:
            titles.append(t)
    if not titles:
        titles = [raw.strip()]
    return {"titles": titles[: max(req.count, 1)]}


@app.post("/api/generate/content")
def generate_content(req: ContentReq, uid: int = Depends(current_user)):
    style_line = f"风格倾向：{req.style}" if req.style else ""
    extra_line = f"补充说明：{req.extra}" if req.extra else ""
    tpl = TEMPLATES.get(req.template, TEMPLATES["general"])
    tpl_line = f"写作模板：{tpl['content']}" if tpl["content"] else ""
    feedback_line = f"【修改要求】{req.feedback}\n请重点满足这条修改要求。" if req.feedback else ""
    previous_line = f"【上一版内容】\n{req.previous_content}\n请基于这版修改，而不是完全重写。" if req.previous_content else ""

    # 素材库：读取选中素材内容供 AI 引用
    mat_segs = []
    for mid in (req.material_ids or []):
        seg = _read_material_text(uid, mid)
        if seg:
            mat_segs.append(seg)
    material_block = ""
    if mat_segs:
        note = f"优化要求：{req.material_note}\n" if (req.material_note or "").strip() else ""
        material_block = (
            "\n【参考资料/素材】请务必结合下面的素材内容来写，引用其中的关键信息、数据或观点。\n"
            + note + "\n\n".join(mat_segs) + "\n"
        )

    user = (
        f"请根据下面的题目和主题，写一篇结构完整、可直接发布的公众号文章。\n\n"
        f"题目：{req.title}\n主题：{req.topic}\n"
        + (style_line + "\n" if style_line else "")
        + (extra_line + "\n" if extra_line else "")
        + (tpl_line + "\n" if tpl_line else "")
        + "\n写作要求：1. 用 Markdown：小标题用 ##，适当列表/加粗/引用 2. 有清晰开头、分点、结尾 "
        "3. 语言自然像真人，避免 AI 腔 4. 篇幅 1000~1800 字\n"
        + (material_block + "\n" if material_block else "")
        + (feedback_line + "\n" if feedback_line else "")
        + (previous_line + "\n" if previous_line else "")
    )
    content = _llm_for(
        uid,
        [{"role": "system", "content": "你是资深公众号写作者，产出可直接发布的文章。"},
         {"role": "user", "content": user}],
        temperature=0.8, max_tokens=4096,
    )
    return {"content": content.strip()}


def _image_refs(images):
    out = []
    for i in images or []:
        if isinstance(i, dict) and i.get("url"):
            out.append({"url": i["url"], "alt": (i.get("alt") or i.get("name") or "配图").strip() or "配图"})
    return out


def _ensure_images(md, images):
    for img in images:
        if img["url"] and img["url"] not in md:
            md = md.rstrip() + f"\n\n![{img['alt']}]({img['url']})"
    return md


@app.post("/api/generate/format")
def generate_format(req: FormatReq, uid: int = Depends(current_user)):
    tpl = TEMPLATES.get(req.template, TEMPLATES["general"])
    images = _image_refs(req.images)
    if req.polish:
        reqs = []
        if req.add_summary:
            reqs.append("- 在正文最前面加一段「导语/摘要」（不超过 60 字）")
        if req.add_golden:
            reqs.append("- 提炼 1~3 句金句，用加粗或引用块突出")
        if req.add_follow:
            reqs.append("- 在结尾加一段自然的「引导关注」语")
        if req.tone:
            reqs.append(f"- 整体语气调整为：{req.tone}")
        if tpl.get("format"):
            reqs.append(tpl["format"])
        if images:
            img_desc = "\n".join(f"{i + 1}. {img['alt']}：{img['url']}" for i, img in enumerate(images))
            reqs.append("把下面的配图插入到正文最相关的位置（Markdown 图片语法，地址原样保留）：\n" + img_desc)
        if not reqs:
            reqs.append("- 优化小标题层级、段落节奏，让重点更突出")
        reqs.append("- 保持原意和事实不变，不新增虚假信息")
        user = "请对下面的文章进行格式优化与润色，只输出优化后的 Markdown 正文，不要多余解释。\n优化要求：\n" + "\n".join(reqs) + "\n\n【原文】\n" + req.content
        md = _llm_for(
            uid,
            [{"role": "system", "content": "你是公众号排版专家。"},
             {"role": "user", "content": user}],
            temperature=0.6, max_tokens=4096,
        ).strip()
    else:
        md = req.content
    md = _ensure_images(md, images)
    html = mh.render_full(req.title, md, req.theme)
    return {"content": md, "html": html}


@app.post("/api/render")
def render(req: RenderReq):
    return {"html": mh.render_full(req.title, req.content, req.theme)}


# ---------------- 文章（按用户隔离） ----------------
class ArticleReq(BaseModel):
    topic: str
    title: str
    content_md: str
    content_html: str = ""
    cover: str = ""
    theme: str = "default"


@app.get("/api/articles")
def list_articles(uid: int = Depends(current_user)):
    return db.list_articles(uid)


@app.post("/api/articles")
def create_article(req: ArticleReq, uid: int = Depends(current_user)):
    html = req.content_html or mh.render_full(req.title, req.content_md, req.theme)
    article_id = db.insert_article(uid, req.topic, req.title, req.content_md, html, req.cover, req.theme)
    _write_article_files(uid, article_id, req.content_md, html)
    return {"id": article_id}


@app.get("/api/articles/{article_id}")
def get_article(article_id: int, uid: int = Depends(current_user)):
    a = db.get_article(uid, article_id)
    if not a:
        raise HTTPException(404, "文章不存在")
    return dict(a)


@app.put("/api/articles/{article_id}")
def update_article(article_id: int, req: ArticleReq, uid: int = Depends(current_user)):
    if not db.get_article(uid, article_id):
        raise HTTPException(404, "文章不存在")
    html = req.content_html or mh.render_full(req.title, req.content_md, req.theme)
    db.update_article(uid, article_id, topic=req.topic, title=req.title,
                      content_md=req.content_md, content_html=html, cover=req.cover, theme=req.theme)
    _write_article_files(uid, article_id, req.content_md, html)
    return {"id": article_id}


@app.delete("/api/articles/{article_id}")
def delete_article(article_id: int, uid: int = Depends(current_user)):
    db.delete_article(uid, article_id)
    return {"ok": True}


@app.post("/api/articles/{article_id}/cover")
async def upload_cover(article_id: int, file: UploadFile = File(...), uid: int = Depends(current_user)):
    if not db.get_article(uid, article_id):
        raise HTTPException(404, "文章不存在")
    ext = os.path.splitext(file.filename or "cover.jpg")[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        ext = ".jpg"
    d = os.path.join(config.ARTICLES_DIR, str(uid), str(article_id))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"cover{ext}")
    data = await file.read()
    with open(path, "wb") as f:
        f.write(data)
    db.update_article(uid, article_id, cover=path)
    return {"ok": True}


def _write_article_files(uid, article_id, md, html):
    d = os.path.join(config.ARTICLES_DIR, str(uid), str(article_id))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "article.md"), "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(d, "article.html"), "w", encoding="utf-8") as f:
        f.write(html)


# ---------------- 数据导出 ----------------
@app.get("/api/export")
def export_data(uid: int = Depends(current_user)):
    articles = [dict(a) for a in db.list_articles(uid)]
    materials = [dict(m) for m in db.list_materials(uid)]
    return {
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "username": db.get_user(uid)["username"],
        "articles": articles,
        "materials": materials,
    }


# ---------------- 素材 ----------------
@app.get("/api/materials")
def list_materials(uid: int = Depends(current_user)):
    items = [dict(r) for r in db.list_materials(uid)]
    for it in items:
        it["url"] = f"/api/materials/{it['id']}/file"
    return items


@app.post("/api/materials")
async def upload_material(file: UploadFile = File(...), uid: int = Depends(current_user)):
    name = os.path.basename(file.filename or "material.txt") or "material.txt"
    base, ext = os.path.splitext(name)
    d = os.path.join(config.MATERIALS_DIR, str(uid))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, name)
    i = 1
    while os.path.exists(path):
        path = os.path.join(d, f"{base}_{i}{ext}")
        i += 1
    data = await file.read()
    with open(path, "wb") as f:
        f.write(data)
    mid = db.insert_material(uid, os.path.basename(path), path, len(data))
    return {"id": mid, "name": os.path.basename(path)}


@app.delete("/api/materials/{material_id}")
def delete_material(material_id: int, uid: int = Depends(current_user)):
    m = db.get_material(uid, material_id)
    if m:
        p = m["path"] or ""
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
        db.delete_material(uid, material_id)
    return {"ok": True}


@app.get("/api/materials/{material_id}/file")
def material_file(material_id: int, uid: int = Depends(current_user)):
    """按用户隔离地访问素材文件本体（供缩略图/预览用）。"""
    m = db.get_material(uid, material_id)
    if not m or not m["path"] or not os.path.exists(m["path"]):
        raise HTTPException(status_code=404, detail="素材不存在")
    return FileResponse(m["path"])


@app.post("/api/materials/{material_id}/use")
def use_material(material_id: int, uid: int = Depends(current_user)):
    """把素材复制进图片库，返回 /images/ 地址，从而可被选图/预览/推送复用。"""
    m = db.get_material(uid, material_id)
    if not m or not m["path"] or not os.path.exists(m["path"]):
        raise HTTPException(status_code=404, detail="素材不存在")
    config.ensure_dirs()
    name = os.path.basename(m["path"])
    base, ext = os.path.splitext(name)
    dest = os.path.join(IMAGES_DIR, name)
    i = 1
    while os.path.exists(dest):
        dest = os.path.join(IMAGES_DIR, f"{base}_{i}{ext}")
        i += 1
    shutil.copyfile(m["path"], dest)
    final = os.path.basename(dest)
    return {"name": final, "url": f"/images/{final}"}


# ---------------- 图片库（MVP 共享） ----------------
class ImageSearchReq(BaseModel):
    query: str


class ImageFetchReq(BaseModel):
    url: str
    thumb: str = ""
    page: str = ""


def _safe_img_ext(ext):
    ext = (ext or "").lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        ext = ".jpg"
    return ext


def _unique_image_path(ext):
    config.ensure_dirs()
    base = f"img_{int(time.time() * 1000)}"
    path = os.path.join(IMAGES_DIR, f"{base}{ext}")
    i = 1
    while os.path.exists(path):
        path = os.path.join(IMAGES_DIR, f"{base}_{i}{ext}")
        i += 1
    return path


@app.get("/api/images")
def list_images():
    config.ensure_dirs()
    items = []
    for name in sorted(os.listdir(IMAGES_DIR)):
        if os.path.splitext(name)[1].lower() not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
            continue
        p = os.path.join(IMAGES_DIR, name)
        if os.path.isfile(p):
            items.append({"name": name, "url": f"/images/{name}", "size": os.path.getsize(p)})
    return items


@app.post("/api/images")
async def upload_images(files: list[UploadFile] = File(...)):
    config.ensure_dirs()
    out = []
    for file in files:
        name = re.sub(r'[\s　]+', '_', os.path.basename(file.filename or "image.jpg") or "image.jpg")
        ext = _safe_img_ext(os.path.splitext(name)[1])
        base = os.path.splitext(name)[0] or "image"
        data = await file.read()
        if not data:
            continue
        path = os.path.join(IMAGES_DIR, f"{base}{ext}")
        i = 1
        while os.path.exists(path):
            path = os.path.join(IMAGES_DIR, f"{base}_{i}{ext}")
            i += 1
        with open(path, "wb") as f:
            f.write(data)
        final = os.path.basename(path)
        out.append({"name": final, "url": f"/images/{final}"})
    return out


@app.delete("/api/images/{name}")
def delete_image(name: str):
    p = os.path.join(IMAGES_DIR, os.path.basename(name))
    if os.path.isfile(p):
        try:
            os.remove(p)
        except OSError:
            pass
    return {"ok": True}


@app.post("/api/images/search")
def search_images(req: ImageSearchReq):
    try:
        return {"results": imagesearch.search(req.query)}
    except imagesearch.SearchError as e:
        raise HTTPException(400, str(e))


@app.post("/api/images/fetch")
def fetch_image(req: ImageFetchReq):
    config.ensure_dirs()
    candidates = [u for u in (req.url, req.thumb) if u]
    if not candidates:
        raise HTTPException(400, "缺少图片地址")
    last_err = None
    for u in candidates:
        try:
            data, ctype = imagesearch.download(u, referer=req.page)
            ext = imagesearch._ext_from_ctype(ctype) or _safe_img_ext(os.path.splitext(u.split("?")[0])[1])
            path = _unique_image_path(ext)
            with open(path, "wb") as f:
                f.write(data)
            return {"name": os.path.basename(path), "url": f"/images/{os.path.basename(path)}"}
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise HTTPException(400, f"图片下载失败：{last_err or '未知错误'}")


# ---------------- 推送草稿箱 ----------------
_IMG_TAG_RE = re.compile(r'<img\s+[^>]*>')
_SRC_RE = re.compile(r'src="([^"]+)"')


def _resolve_wechat_images(appid, appsecret, html):
    def repl(tag):
        m = _SRC_RE.search(tag.group(0))
        if not m:
            return tag.group(0)
        src = m.group(1)
        name = os.path.basename(src.split("?")[0].rstrip("/"))
        local = os.path.join(IMAGES_DIR, name)
        if not os.path.exists(local):
            return tag.group(0)
        try:
            wechat_url = wechat.upload_image(appid, appsecret, local)
        except wechat.WeChatError:
            return tag.group(0)
        if not wechat_url:
            return tag.group(0)
        attrs = tag.group(0)
        if 'data-src="' in attrs:
            attrs = attrs.replace(m.group(0), f'src="{wechat_url}"')
        else:
            attrs = attrs.replace(m.group(0), f'data-src="{wechat_url}" src="{wechat_url}"')
        return attrs
    return _IMG_TAG_RE.sub(repl, html)


def _truncate_bytes(s, max_bytes):
    """按 UTF-8 字节数截断，不切碎多字节字符（中文 1 字 = 3 字节）。"""
    b = s.encode("utf-8")
    if len(b) <= max_bytes:
        return s
    out, total = [], 0
    for ch in s:
        bl = len(ch.encode("utf-8"))
        if total + bl > max_bytes:
            break
        out.append(ch)
        total += bl
    return "".join(out)


def _plain_digest(md, max_bytes=120):
    """从正文生成摘要，按字节截到微信 description 上限（120 字节 ≈ 40 汉字）。"""
    text = re.sub(r'[#>*`\-]', '', md)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return _truncate_bytes(text, max_bytes)


@app.post("/api/articles/{article_id}/push")
def push_draft(article_id: int, uid: int = Depends(current_user)):
    article = db.get_article(uid, article_id)
    if not article:
        raise HTTPException(404, "文章不存在")
    s = _user_settings(uid)
    cover = article["cover"] or ""
    if not cover or not os.path.exists(cover):
        if os.path.exists(DEFAULT_COVER):
            cover = DEFAULT_COVER
        else:
            raise HTTPException(400, "缺少封面图，请先上传封面。")
    try:
        thumb = wechat.upload_thumb(s.get("wechat_appid", ""), s.get("wechat_appsecret", ""), cover)
        html = article["content_html"] or mh.render_full(article["title"], article["content_md"], article["theme"])
        html = _resolve_wechat_images(s.get("wechat_appid", ""), s.get("wechat_appsecret", ""), html)
        draft = {
            "title": article["title"],
            "author": s.get("wechat_author", ""),
            "digest": _plain_digest(article["content_md"]),
            "content": html,
            "content_source_url": s.get("wechat_source_url", ""),
            "thumb_media_id": thumb,
            "need_open_comment": int(s.get("wechat_need_open_comment", 0) or 0),
            "only_fans_can_comment": int(s.get("wechat_only_fans_can_comment", 0) or 0),
        }
        media_id = wechat.add_draft(s.get("wechat_appid", ""), s.get("wechat_appsecret", ""), draft)
        db.update_article(uid, article_id, status="pushed")
        return {"ok": True, "draft_media_id": media_id}
    except wechat.WeChatError as e:
        raise HTTPException(400, str(e))


@app.get("/api/wechat/ip")
def wechat_ip():
    return {"ips": wechat.get_public_ips()}


# ---------------- 静态资源 ----------------
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/images", StaticFiles(directory=config.IMAGES_DIR), name="images")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

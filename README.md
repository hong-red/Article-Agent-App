# 智能精灵 · App（托管版 PWA）

面向小白的**托管版**公众号文章生成器。在网页版基础上新增：**登录注册（邀请码）、密钥加密存储、按用户隔离、数据导出**。

> ⚠️ 免费期至 **2026-12**（占位，正式上线前改 `config.py` 的 `FREE_UNTIL`）。到期后用户可自行导出数据迁移。

## ✨ 与网页版的区别

| | 网页版（自托管） | App 版（托管） |
|---|---|---|
| 面向 | 技术用户 | 小白 |
| 部署 | 用户自己一键部署 | 托管方部署，多用户 |
| 密钥 | 存用户自己机器 | 服务端**加密**存储 |
| 鉴权 | 一个访问口令 | 账号密码 + 邀请码 |
| 数据 | 本地 | 服务端，按用户隔离，可导出 |

## 🚀 部署

```bash
git clone https://github.com/hong-red/Article-Agent-App.git
cd Article-Agent-App
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
```

首次启动会自动生成一个默认邀请码并打印到日志（`SMART2026`）。也可以用 CLI 管理邀请码：

```bash
.venv/bin/python manage.py invite 你的邀请码   # 新增邀请码
.venv/bin/python manage.py list               # 列出邀请码
```

## 🔐 安全设计

- **密码**：PBKDF2 加盐散列，不存明文。
- **用户密钥**（DeepSeek Key / 公众号 Secret）：用 Fernet 对称加密后存 SQLite，密钥文件 `data/secret.key`（首次启动自动生成，勿泄露）。
- **会话**：登录发随机 token，前端放 localStorage，请求带 `Authorization: Bearer <token>`。
- **数据隔离**：文章/素材按 `user_id` 隔离，互不可见。

## 🔌 API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/register` | 注册（用户名/密码/邀请码） |
| POST | `/api/auth/login` | 登录，返回 token |
| GET | `/api/auth/me` | 当前用户 |
| POST | `/api/auth/logout` | 退出 |
| GET | `/api/info` | 应用信息（免费期） |
| GET/POST | `/api/settings` | 读取/保存用户设置（加密） |
| POST | `/api/generate/titles` `/content` `/format` | 生成 |
| POST | `/api/render` | Markdown → HTML |
| GET/POST/PUT/DELETE | `/api/articles` | 文章（按用户隔离） |
| POST | `/api/articles/{id}/push` | 推送到草稿箱 |
| GET | `/api/export` | 导出当前用户全部数据 |
| GET/POST/DELETE | `/api/images` `/api/materials` | 图片/素材 |

## 📱 PWA

前端是纯静态页（`static/`），带 `manifest.json` + `sw.js`，手机浏览器打开后可「添加到主屏」，像 App 一样使用。

## 📂 结构

```text
├── app.py         # FastAPI 后端（认证 + 生成 + 文章 + 导出）
├── db.py          # SQLite：用户/会话/邀请码/文章/素材
├── crypto.py      # 密码散列 + 密钥加密
├── config.py      # 配置（数据目录、免费期）
├── manage.py      # 邀请码管理 CLI
├── llm.py imagesearch.py markdown_html.py wechat.py  # 复用网页版
└── static/        # 前端 PWA（index.html / app.js / style.css / manifest.json / sw.js）
```

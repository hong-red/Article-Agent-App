"""邀请码管理：python manage.py invite <邀请码> [可注册次数]  或  python manage.py list"""
import sys

import db


def main():
    db.init_db()
    if len(sys.argv) < 2:
        print("用法：python manage.py invite <邀请码> [可注册次数]  或  python manage.py list")
        return
    cmd = sys.argv[1]
    if cmd == "invite":
        if len(sys.argv) < 3:
            print("请提供邀请码：python manage.py invite ABC123 [200]")
            return
        code = sys.argv[2].strip()
        if not code:
            print("邀请码不能为空")
            return
        max_uses = int(sys.argv[3]) if len(sys.argv) > 3 else 200
        db.add_invite_code(code, max_uses=max_uses)
        print(f"已添加邀请码：{code}（可注册 {max_uses} 次）")
    elif cmd == "list":
        codes = db.list_invite_codes()
        if not codes:
            print("暂无邀请码")
            return
        for c in codes:
            print(f"{c['code']}  已用={c['used']}/{c['max_uses']}  使用人={c['used_by'] or '-'}")
    else:
        print("未知命令")


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
from pathlib import Path

# DeepSeek 直接输出可发到飞书/企微的全文（见 NOTIFY_FORMAT=ai）
DEFAULT_SUMMARY = """你是邮件助理。请阅读用户提供的完整邮件头与正文，用简体中文生成「可直接发到飞书/企业微信」的纯文本通知。

【输出格式】必须严格遵守，不要加 markdown 代码块，不要任何开场白或结尾废话：

📬 新邮件总结 [{account}]
━━━━━━━━━━━━━━
转发自：（判断这封信是经用户哪个邮箱转发/代收来的；从正文转发块、To、Received 等推断；若直达汇总邮箱写「直连」；无法判断写「未知」）
发件人：（真正写这封信的人或系统；看 From 或转发块内的 From，不要填成「转发自」里的邮箱）
主题：（原邮件主题；若有 Fwd 转发，用内层真实主题）
时间：（邮件 Date，无则写「未知」）
━━━━━━━━━━━━━━
（此处 3-5 句话概括核心内容，不要编造）

待办：
- （若有明确待办逐条列出，标明时间地点任务等；若无写「无」）

【规则】
1. 不要编造邮件中没有的信息
2. 「转发自」= 用户自己的哪个邮箱收到后转来；「发件人」= 谁写的信，二者不要混淆
3. 忽略签名、免责声明、退订链接
4. 招聘/面试类邮件要提炼关键信息
5. 如果活动有报名链接，要提取报名链接"""

DEFAULT_FILTER = """判断这封邮件是否值得推送给用户做中文总结。
应跳过（回答 SKIP）：
- 登录/注册/支付用的一次性验证码、OTP、安全码邮件
- 纯营销促销、无实质内容的系统自动通知
- 关于域名过期或者订阅续费类的邮件
- 证券账户发的日常通告类邮件
应保留（回答 KEEP）：
- 工作沟通、客户/同事/上级来信、面试与会议、求职与招聘
- 招聘类的广告邮件
- 账单/订单/行程等需用户知晓的事项（非纯广告）
- 正文中提到「短信」「验证」但实质是工作反馈、安排或讨论的邮件
原则：不确定时回答 KEEP，宁可多推送也不要漏掉重要邮件。
只回答 KEEP 或 SKIP，可加半句理由。"""


def prompts_path(data_dir: Path | None = None) -> Path:
    base = data_dir or Path("./data")
    return base / "prompts.json"


def load_prompts(data_dir: Path | None = None) -> dict[str, str]:
    path = prompts_path(data_dir)
    if not path.exists():
        return {
            "summary_system": DEFAULT_SUMMARY,
            "filter_system": DEFAULT_FILTER,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "summary_system": data.get("summary_system") or DEFAULT_SUMMARY,
            "filter_system": data.get("filter_system") or DEFAULT_FILTER,
        }
    except (json.JSONDecodeError, OSError):
        return {
            "summary_system": DEFAULT_SUMMARY,
            "filter_system": DEFAULT_FILTER,
        }


def save_prompts(
    summary_system: str,
    filter_system: str,
    data_dir: Path | None = None,
) -> None:
    path = prompts_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "summary_system": summary_system.strip(),
                "filter_system": filter_system.strip(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

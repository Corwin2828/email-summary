#!/bin/bash
# 双击打开网页配置（Prompt / API / 邮箱 / Webhook）
cd "$(dirname "$0")"

echo "======================================"
echo "  邮件总结助手 · 设置页"
echo "  保存后请重启「启动邮件助手」"
echo "======================================"
echo ""

chmod +x settings.sh 2>/dev/null
bash settings.sh
code=$?

echo ""
read -r -p "按回车键关闭此窗口…" _

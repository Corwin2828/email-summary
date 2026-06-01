#!/bin/bash
# 双击此文件即可在终端中启动邮件总结助手（macOS）
cd "$(dirname "$0")"

echo "======================================"
echo "  邮件总结助手"
echo "  正在启动…（关闭请在本窗口按 Ctrl+C）"
echo "======================================"
echo ""

chmod +x run.sh 2>/dev/null
bash run.sh
code=$?

echo ""
if [[ $code -ne 0 ]]; then
  echo "程序异常退出，代码: $code"
else
  echo "程序已结束。"
fi
read -r -p "按回车键关闭此窗口…" _

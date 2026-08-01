
<div align="center">

![:name](https://count.getloli.com/@astrbot_plugin_qun_album?name=astrbot_plugin_qun_album&theme=minecraft&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

# astrbot_plugin_qun_album

_✨ [astrbot](https://github.com/AstrBotDevs/AstrBot) 群相册插件 ✨_  

[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-3.4%2B-orange.svg)](https://github.com/AstrBotDevs/AstrBot)
[![GitHub](https://img.shields.io/badge/作者-Zhalslar-blue)](https://github.com/Zhalslar)

</div>

## 🤝 介绍

- 本插件利用 aiocqhttp 协议端 提供的群相册接口，快速把群友的怪话“截图”上传到群相册中，并支持通过相册名随机获取已上传的群相册图片。

## 📦 安装

- 可以直接在astrbot的插件市场搜索astrbot_plugin_qun_album，点击安装，耐心等待安装完成即可  

- 或者可以直接克隆源码到插件文件夹：

```bash
# 克隆仓库到插件目录
cd /AstrBot/data/plugins
git clone https://github.com/Zhalslar/astrbot_plugin_qun_album

# 控制台重启AstrBot
```

## ⌨️ 使用说明

### 命令表

| 命令 | 功能描述 |
|------|----------|
| (引用消息)上传群相册 | 将图片/文字meme上传到群相册中，命令别名：up |
| (引用消息)上传群相册 [相册名] [数量] | 将回复的消息及其之上的指定数量文本消息生成拼接图上传 |
| 群相册名 | 在配置了 `random_album_groups` 的群中，直接发送相册名随机获取一张相册图片 |

### 效果图

![download](https://github.com/user-attachments/assets/9a991c7a-7943-41a5-98f0-8e668cebe3fa)

## 📝 字体说明

### 自动下载

插件首次启动时会从 CDN 自动下载字体（`NotoSansSC-Regular.ttf` / `NotoSansSC-Bold.ttf`）并缓存到 `<AstrBot数据目录>/data/astrbot_plugin_qun_album/fonts/`。

### 手动安装（CDN 不可用时的备用方案）

如果 CDN 下载失败，可以手动下载字体解压放入上述字体目录：

1. 前往 [Google Noto Sans SC GitHub Release](https://github.com/googlefonts/noto-cjk/releases/tag/Sans2.004) 下载 `18_NotoSansSC.zip`（Region Specific Subset OTFs Simplified Chinese）
2. 解压后将 `NotoSansSC-Regular.otf` 和 `NotoSansSC-Bold.otf` 放入 `<AstrBot数据目录>/data/astrbot_plugin_qun_album/fonts/` 目录下
3. 重启插件或 AstrBot，插件会自动加载字体

支持 `.ttf` 和 `.otf` 两种格式。

## 📌 注意事项

- 本插件要求 NapCat 版本不小于 4.8.100，其他版本或协议端可能会存在一些不兼容问题（以具体情况为准）
- 群相册随机发图需同时启用 `backup_media` 和 `random_album_groups`
- 想第一时间得到反馈的可以来作者的插件反馈群（QQ群）：460973561（不点star不给进）

## 👥 贡献指南

- 🌟 Star 这个项目！（点右上角的星星，感谢支持！）
- 🐛 提交 Issue 报告问题
- 💡 提出新功能建议
- 🔧 提交 Pull Request 改进代码

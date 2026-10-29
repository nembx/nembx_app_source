# nembx 软件源

个人收集的 iOS 应用目录，供 SideStore / AltStore 使用。

## 添加软件源

在 SideStore 的 Sources（来源）页面添加下面的网址：

```text
https://raw.githubusercontent.com/nembx/nembx_app_source/main/source.json
```

仓库需要保持公开，这样 SideStore 才能直接读取。无需服务器或开启 GitHub Pages。
下载链接直接指向作者的官方 Release。尚未经过 SideStore 真机添加验证。

| 应用 | 当前版本 | 最低 iOS（读取自 IPA） | 官方项目 |
| --- | --- | --- | --- |
| CiliCili | 1.1.1 | 26.1 | [Rone89/cilicili](https://github.com/Rone89/cilicili) |
| 贴吧 Lite | 2.2.0 | 17.0 | [toamdou/TiebaLite-IOS](https://github.com/toamdou/TiebaLite-IOS) |

## 自动跟踪更新

已在 `upstreams.json` 配置跟踪上述项目的正式 Release：

1. GitHub Actions 每 6 小时检查一次最新正式 Release（UTC 00:23、06:23、12:23、18:23，北京时间 08:23、14:23、20:23、次日 02:23）。调度可能延迟，并非实时监听。
2. 发现新增或被替换的匹配 IPA 后，下载并读取真实元数据，同步版本、大小、最低系统要求和更新说明，自动提交软件源。
3. SideStore 下次刷新来源时即可读到更新；安装更新仍由客户端处理。

可随时在 **Actions → 检查上游应用更新 → Run workflow** 手动检查。没有新版本时不会重复下载或提交。预发布和草稿不收录；最新 Release 暂无 IPA 时保留当前版本，等下次检查。

要跟踪更多项目，在 `upstreams.json` 的 `repositories` 数组中增加对象，填写 `repo`、`assetPattern`、`name`、`developer`、`description` 和可选的 `iconURL`。模式必须只匹配一个 IPA；例如 `*-unsigned.ipa`。首次运行后会自动生成 `lastRelease`，无需手填。

`assetPattern` 支持 `{tag}` 占位符，检查时会替换成当前 Release 标签。例如贴吧 Lite 使用 `TiebaLite-{tag}.ipa`，在 `v2.2.0` 中只匹配 `TiebaLite-v2.2.0.ipa`，避免选中其他系统变体。

仅使用“添加或更新应用”入口添加的直链应用不会自动跟踪；需要在 `upstreams.json` 中另外配置 GitHub 仓库。纯直链没有统一的版本查询方式。

GitHub 可能在公开仓库长期无活动（通常 60 天）后停用定时工作流。请留意 Actions 状态，必要时重新启用。仓库必须开启 Actions，定时任务只在默认分支执行。

## 通过 GitHub 网页收录应用

1. 打开仓库的 **Actions → 添加或更新应用 → Run workflow**，选择 `main` 分支。
2. 填写 **IPA 的公开 HTTPS 下载直链**，可选填应用图标、显示名称、开发者和介绍。
3. 点击 **Run workflow**，等待任务变绿。任务会下载 IPA、读取元数据，并自动提交更新后的 `source.json`。
4. 在 SideStore 中刷新软件源。

同一个 Bundle ID 会归到同一应用。每次提交的 IPA 会成为最新版本；相同版本号会被替换，其他历史版本保留。因此添加旧版本时应手动调整 `versions` 的顺序。

下载地址必须无需登录即可直接返回 IPA。分享页面、`github.com/.../blob/...` 页面和需要 Cookie 的链接不能使用。建议选择长期有效的链接；软件源只记录链接，不会把 IPA 重新托管到此仓库。默认最多下载 2 GiB。

没有独立图标时暂用软件源图标；之后可编辑 `source.json` 的 `iconURL`。推荐使用公开的 PNG 图标链接。开发者名称不会从 IPA 中可靠推断，首次收录建议填写。

## 在电脑上收录应用

只需要 Python 3.9 或更新版本，无需安装第三方库：

```bash
python3 scripts/add_app.py \
  --url 'https://example.com/App.ipa' \
  --icon-url 'https://example.com/icon.png' \
  --developer '开发者名称' \
  --description '应用介绍'
```

也可以读取本地 IPA，指定它在网上的下载地址：

```bash
python3 scripts/add_app.py \
  --ipa '/path/to/App.ipa' \
  --download-url 'https://example.com/App.ipa'
```

本地修改后提交并推送：

```bash
git add source.json
git commit -m "Update app source"
git push origin main
```

## 自定义

- 源名称、简介、图标与主题颜色：编辑 `source.json` 顶部字段。
- 删除应用：从 `apps` 数组移除对应对象。
- 版本说明：在对应版本中添加 `localizedDescription`。
- 同一应用的版本数组按从新到旧排列。

源文件同时生成 `versions` 数组与旧格式的版本字段，便于不同客户端读取。
最低 iOS 版本来自 IPA；JSON 格式正确并不代表 IPA 一定能安装，签名、权限声明和设备兼容性仍需在实际客户端验证。

## 常见问题

- **找不到 Run workflow**：确认文件已推送到 `main`，并在 Actions 页面允许运行工作流。
- **更新失败**：查看 Actions 中失败步骤；常见原因是网址返回网页、下载链接过期或 IPA 缺少有效的主应用 `Info.plist`。
- **提交时报 403**：检查仓库/组织的 Actions 权限策略。此工作流声明了 `contents: write`，但更高层策略仍可能禁止写入。
- **刷新后尚未变化**：GitHub Raw 有缓存，稍后再刷新。

请仅收录你有权分发的应用。软件源提供目录和下载地址，应用仍由 SideStore 按其签名流程安装。

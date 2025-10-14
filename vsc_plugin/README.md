# Stealth Monitor Notebook Tools

这个 VS Code 扩展会在 Jupyter 笔记本工具栏增加一个「运行两个步骤」按钮，点击后可一次执行两个指定的单元格。

## 使用说明

1. 将整个 `vsc_plugin` 目录作为 VS Code 扩展工程打开，执行 `npm install`（如有需要）后按 `F5` 以扩展宿主方式启动，或直接使用 `vsce package` 进行打包。
2. 在 `settings.json` 中配置 `stealthMonitorJupyter.targetCells`，值为要执行的单元格索引数组（从 `0` 开始计数）。例如：

   ```json
   {
     "stealthMonitorJupyter.targetCells": [6, 7]
   }
   ```

   如果不设置，会自动寻找带有 `stealth-run:<序号>` 标签或 `metadata.custom.stealthRunOrder` 的单元格，按序号排序后取前两个执行。
3. 打开任意 `.ipynb` 文件，顶部工具栏会出现「运行两个步骤」按钮，点击即可运行配置的两个单元格。

## 调试

- 使用 VS Code 的「运行和调试」面板，选择 “Run Extension”。
- 在扩展宿主窗口中打开目标笔记本并测试按钮行为。

## 提示

- 如果未来需要执行超过两个单元格，可以在 `extension.js` 中调整 `indices.slice(0, 2)` 的逻辑。
- 如需自定义按钮图标，可在 `package.json` 的 `commands` 项中更改 `icon` 属性。

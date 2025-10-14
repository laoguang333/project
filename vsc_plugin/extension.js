// -*- coding: utf-8 -*-
const vscode = require('vscode');

/**
 * 解析单元格元数据，寻找自定义执行顺序。
 * 支持两种写法：
 * 1. cell.metadata.custom.stealthRunOrder = number
 * 2. cell.metadata.tags 包含类似 "stealth-run:1" 的标签
 * @param {vscode.NotebookCell} cell
 * @returns {number|undefined}
 */
function resolveOrderFromMetadata(cell) {
    if (!cell || !cell.metadata) {
        return undefined;
    }

    const meta = cell.metadata;
    const custom = meta.custom;
    if (custom && typeof custom.stealthRunOrder === 'number') {
        return custom.stealthRunOrder;
    }

    const tags = Array.isArray(meta?.tags) ? meta.tags : [];
    for (const tag of tags) {
        if (typeof tag !== 'string') {
            continue;
        }
        const matched = /^stealth-run:(\d+)$/i.exec(tag.trim());
        if (matched) {
            return Number.parseInt(matched[1], 10);
        }
    }

    return undefined;
}

/**
 * 根据设置或元数据获取目标单元格索引。
 * @param {vscode.NotebookDocument} document
 * @returns {number[]}
 */
function getTargetCellIndices(document) {
    const config = vscode.workspace.getConfiguration('stealthMonitorJupyter');
    const configured = config.get('targetCells');
    if (Array.isArray(configured) && configured.length > 0) {
        return configured
            .map((value) => Number.parseInt(value, 10))
            .filter((value) => Number.isInteger(value) && value >= 0);
    }

    const cells = document.getCells();
    const withOrder = cells
        .map((cell, index) => ({ index, order: resolveOrderFromMetadata(cell) }))
        .filter((item) => typeof item.order === 'number')
        .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
        .map((item) => item.index);

    return withOrder;
}

/**
 * 依次执行指定索引的单元格。
 * @param {vscode.NotebookEditor} editor
 * @param {number[]} indices
 */
async function runNotebookCells(editor, indices) {
    const document = editor.document;
    const available = document.cellCount;

    for (const rawIdx of indices) {
        const idx = Math.trunc(rawIdx);
        if (Number.isNaN(idx) || idx < 0 || idx >= available) {
            continue;
        }

        const range = { start: idx, end: idx + 1 };
        try {
            // 聚焦单元格，方便用户看到执行状态
            await vscode.commands.executeCommand('notebook.cell.focus', { ranges: [range], document });
        } catch (error) {
            // 如果焦点命令不可用，忽略报错
        }

        await vscode.commands.executeCommand('notebook.cell.execute', {
            document,
            ranges: [range]
        });
    }
}

/**
 * 激活扩展。
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
    const disposable = vscode.commands.registerCommand('stealthMonitor.runTwoCells', async () => {
        const editor = vscode.window.activeNotebookEditor;
        if (!editor) {
            vscode.window.showWarningMessage('未找到活动的 Jupyter 笔记本，请先激活一个 .ipynb 文件。');
            return;
        }

        const indices = getTargetCellIndices(editor.document);
        if (!indices || indices.length === 0) {
            vscode.window.showWarningMessage('未检测到要执行的单元格。请在设置中配置 stealthMonitorJupyter.targetCells，或为目标单元格添加 stealth-run:数字 标签。');
            return;
        }

        // 只执行前两个，以满足“两个单元格”的需求，同时给出提示
        const selected = indices.slice(0, 2);
        if (indices.length > 2) {
            vscode.window.setStatusBarMessage('已选择前两个带标记的单元格执行。', 3000);
        }

        await runNotebookCells(editor, selected);
    });

    context.subscriptions.push(disposable);
}

function deactivate() {
    // 无需清理资源
}

module.exports = {
    activate,
    deactivate
};

const fs = require("fs");
const path = require("path");
const vscode = require("vscode");

let diagnosticCollection;
let findingsData = new Map();

function activate(context) {
  diagnosticCollection = vscode.languages.createDiagnosticCollection("the-code-sheriff");
  const refresh = () => loadDiagnostics(diagnosticCollection);
  context.subscriptions.push(
    vscode.commands.registerCommand("theCodeSheriff.refresh", refresh),
    vscode.commands.registerCommand("theCodeSheriff.fix", fixFinding),
    vscode.commands.registerCommand("theCodeSheriff.explain", explainFinding),
    vscode.commands.registerCommand("theCodeSheriff.openReport", openReport),
    vscode.commands.registerCommand("theCodeSheriff.oracle", runOracle),
    diagnosticCollection,
    vscode.languages.registerCodeActionsProvider("*", new SheriffCodeActionProvider(), {
      providedCodeActionKinds: [vscode.CodeActionKind.QuickFix],
    }),
    vscode.languages.registerCodeLensProvider("*", new SheriffCodeLensProvider()),
  );
  refresh();
}

function loadDiagnostics(collection) {
  const folders = vscode.workspace.workspaceFolders || [];
  collection.clear();
  findingsData.clear();
  for (const folder of folders) {
    const report = path.join(folder.uri.fsPath, ".quality-reports", "diagnostics.json");
    if (!fs.existsSync(report)) continue;
    let payload;
    try {
      payload = JSON.parse(fs.readFileSync(report, "utf8"));
    } catch {
      continue;
    }
    const items = payload.diagnostics || payload.findings || [];
    const byFile = new Map();
    for (const item of items) {
      if (!item.path) continue;
      const file = path.join(folder.uri.fsPath, item.path);
      const list = byFile.get(file) || [];
      const line = Math.max(0, (item.line || 1) - 1);
      const range = new vscode.Range(line, 0, line, 200);
      const severity =
        item.severity === "error"
          ? vscode.DiagnosticSeverity.Error
          : item.severity === "warning"
            ? vscode.DiagnosticSeverity.Warning
            : vscode.DiagnosticSeverity.Information;
      const diag = new vscode.Diagnostic(range, item.message || "finding", severity);
      diag.source = "The Code Sheriff";
      diag.code = item.rule || "sheriff";
      diag.severity = severity;
      list.push(diag);
      const key = `${file}:${item.line || 1}`;
      findingsData.set(key, {
        rule: item.rule,
        message: item.message,
        severity: item.severity,
        path: item.path,
        line: item.line,
        suggestion: item.suggestion,
        patch: item.patch,
        verify: item.verify,
        reason: item.reason,
        confidence: item.confidence,
      });
    }
    for (const [file, list] of byFile) {
      collection.set(vscode.Uri.file(file), list);
    }
  }
}

async function fixFinding(uri, range, diagnostic) {
  const key = `${uri.fsPath}:${range.start.line + 1}`;
  const finding = findingsData.get(key);
  if (!finding) {
    vscode.window.showInformationMessage("No fix available for this finding.");
    return;
  }
  if (finding.patch) {
    const choice = await vscode.window.showInformationMessage(
      `Apply fix for "${finding.rule || "finding"}"?`,
      "Apply",
      "Cancel",
    );
    if (choice === "Apply") {
      const terminal = vscode.window.createTerminal("Code Sheriff Fix");
      terminal.sendText(`codesheriff apply --id "${finding.rule || ""}" --path "${finding.path}"`);
      terminal.show();
    }
  } else if (finding.suggestion) {
    const editor = vscode.window.activeTextEditor;
    if (editor) {
      const edit = new vscode.WorkspaceEdit();
      const line = range.start.line;
      edit.replace(uri, new vscode.Range(line, 0, line, 200), finding.suggestion);
      vscode.workspace.applyEdit(edit);
    }
  } else {
    vscode.window.showInformationMessage(
      `Rule: ${finding.rule}\n${finding.reason || finding.message}\n\nRun: codesheriff oracle --prompt`,
    );
  }
}

async function explainFinding(uri, range, diagnostic) {
  const key = `${uri.fsPath}:${range.start.line + 1}`;
  const finding = findingsData.get(key);
  if (!finding) {
    vscode.window.showInformationMessage("No explanation available.");
    return;
  }
  const parts = [
    `**${finding.rule || "Finding"}** (${finding.severity})`,
    "",
    finding.message,
    "",
    finding.reason ? `Why: ${finding.reason}` : "",
    finding.suggestion ? `Fix: ${finding.suggestion}` : "",
    finding.confidence ? `Confidence: ${finding.confidence}` : "",
    "",
    finding.verify ? `Verify: \`${finding.verify}\`` : "",
    "",
    "Run `codesheriff oracle --prompt` for a fix playbook.",
  ].filter(Boolean);
  const panel = vscode.window.createWebviewPanel(
    "sheriffExplain",
    "Code Sheriff — Finding",
    vscode.ViewColumn.Beside,
    { enableScripts: false },
  );
  panel.webview.html = `<!DOCTYPE html><html><head><style>
    body{font-family:var(--vscode-font-family);padding:1rem;color:var(--vscode-foreground);background:var(--vscode-editor-background)}
    code{background:var(--vscode-textCodeBlock-background);padding:0.1rem 0.3rem;border-radius:3px}
    pre{background:var(--vscode-textCodeBlock-background);padding:0.75rem;border-radius:4px;overflow-x:auto}
  </style></head><body>${formatMarkdown(parts.join("\n"))}</body></html>`;
}

function openReport() {
  const folders = vscode.workspace.workspaceFolders || [];
  for (const folder of folders) {
    const report = path.join(folder.uri.fsPath, ".quality-reports", "quality-report.html");
    if (fs.existsSync(report)) {
      vscode.env.openExternal(vscode.Uri.file(report));
      return;
    }
  }
  vscode.window.showInformationMessage("No quality report found. Run `codesheriff run` first.");
}

async function runOracle() {
  const terminal = vscode.window.createTerminal("Code Sheriff Oracle");
  terminal.sendText("codesheriff oracle --prompt");
  terminal.show();
}

function formatMarkdown(text) {
  return text
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br>");
}

class SheriffCodeActionProvider {
  provideCodeActions(document, range, context, token) {
    const actions = [];
    for (const diag of context.diagnostics) {
      if (diag.source !== "The Code Sheriff") continue;
      const key = `${document.uri.fsPath}:${diag.range.start.line + 1}`;
      const finding = findingsData.get(key);
      if (!finding) continue;

      if (finding.patch || finding.suggestion) {
        const fixAction = new vscode.CodeAction(
          `Fix: ${finding.rule || diag.message.slice(0, 40)}`,
          vscode.CodeActionKind.QuickFix,
        );
        fixAction.command = {
          command: "theCodeSheriff.fix",
          title: "Fix finding",
          arguments: [document.uri, diag.range, diag],
        };
        actions.push(fixAction);
      }

      const explainAction = new vscode.CodeAction(
        `Explain: ${finding.rule || "finding"}`,
        vscode.CodeActionKind.QuickFix,
      );
      explainAction.command = {
        command: "theCodeSheriff.explain",
        title: "Explain finding",
        arguments: [document.uri, diag.range, diag],
      };
      actions.push(explainAction);

      if (finding.verify) {
        const verifyAction = new vscode.CodeAction(
          `Verify: ${finding.verify}`,
          vscode.CodeActionKind.QuickFix,
        );
        verifyAction.command = {
          command: "theCodeSheriff.fix",
          title: "Verify fix",
          arguments: [document.uri, diag.range, diag],
        };
        actions.push(verifyAction);
      }
    }
    return actions;
  }
}

class SheriffCodeLensProvider {
  provideCodeLenses(document, token) {
    const lenses = [];
    const diagnostics = vscode.languages.getDiagnostics(document.uri);
    for (const diag of diagnostics) {
      if (diag.source !== "The Code Sheriff") continue;
      const key = `${document.uri.fsPath}:${diag.range.start.line + 1}`;
      const finding = findingsData.get(key);
      if (!finding) continue;

      const fixLens = new vscode.CodeLens(diag.range, {
        title: "Fix",
        command: "theCodeSheriff.fix",
        arguments: [document.uri, diag.range, diag],
      });
      lenses.push(fixLens);

      const explainLens = new vscode.CodeLens(diag.range, {
        title: "Explain",
        command: "theCodeSheriff.explain",
        arguments: [document.uri, diag.range, diag],
      });
      lenses.push(explainLens);
    }
    return lenses;
  }
}

function deactivate() {
  return undefined;
}

module.exports = { activate, deactivate };

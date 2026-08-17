import fs from "node:fs";
import ts from "typescript";

const payload = JSON.parse(fs.readFileSync(0, "utf8") || "{}");
const source = String(payload.source || "");
const maxChars = Number(payload.max_chars || 40000);

const fail = (reason, detail = "") => {
  process.stdout.write(JSON.stringify({ok: false, reason, detail}));
  process.exit(0);
};

if (!source.trim()) fail("missing_source");
if (source.length > maxChars) fail("source_too_large", `${source.length} > ${maxChars}`);
if (!/\breturn\s*[<(]/.test(source)) fail("missing_return");

const hardBlocked = [
  /\b(import|export)\b/,
  /\b(require|process|globalThis|window|document|navigator|location)\b/,
  /\b(fetch|XMLHttpRequest|WebSocket|Worker|SharedWorker|EventSource)\b/,
  /\b(eval|Function|setTimeout|setInterval|queueMicrotask)\b/,
  /\b(__proto__|prototype|constructor)\b/,
  /\b(Date|Math\s*\.\s*random)\b/,
  /\b(staticFile|dangerouslySetInnerHTML)\b/,
  /\b(data:|javascript:|https?:\/\/|file:)/i,
  /(?:^|["'`\s])url\s*\(/i,
];
for (const pattern of hardBlocked) {
  if (pattern.test(source)) fail("blocked_token", pattern.source);
}

const wrapped = `const __Scene = ({scene, brand, palette, frame, fps, width, height, durationInFrames, interpolate, interpolateColors, spring, Easing, seededRandom, AbsoluteFill, Sequence, CameraMotionBlur, ProtectedMedia, BrandLogo}) => {\n${source}\n};`;
const file = ts.createSourceFile("generated-scene.tsx", wrapped, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TSX);
if (file.parseDiagnostics.length) {
  fail(
    "syntax_error",
    file.parseDiagnostics.map((item) => ts.flattenDiagnosticMessageText(item.messageText, " ")).join("; ").slice(0, 500),
  );
}

const allowedJsx = new Set([
  "div", "span", "svg", "path", "circle", "rect", "line", "g", "defs",
  "linearGradient", "radialGradient", "stop", "polygon", "polyline", "text",
  "mask", "clipPath", "AbsoluteFill", "Sequence", "CameraMotionBlur", "ProtectedMedia", "BrandLogo",
]);
const allowedCalls = new Set([
  "interpolate", "interpolateColors", "spring", "seededRandom", "String", "Number",
  "Math.abs", "Math.ceil", "Math.cos", "Math.floor", "Math.max", "Math.min",
  "Math.pow", "Math.round", "Math.sin", "Math.sqrt", "Math.tan",
  "Array.from",
]);
const allowedMethods = new Set([
  "map", "filter", "slice", "join", "split", "includes", "indexOf", "charAt",
  "toFixed", "toLowerCase", "toUpperCase", "trim", "replace",
]);
const blockedKinds = new Set([
  ts.SyntaxKind.ImportDeclaration,
  ts.SyntaxKind.ImportEqualsDeclaration,
  ts.SyntaxKind.ExportAssignment,
  ts.SyntaxKind.ExportDeclaration,
  ts.SyntaxKind.ClassDeclaration,
  ts.SyntaxKind.NewExpression,
  ts.SyntaxKind.AwaitExpression,
  ts.SyntaxKind.YieldExpression,
  ts.SyntaxKind.WithStatement,
  ts.SyntaxKind.DebuggerStatement,
  ts.SyntaxKind.WhileStatement,
  ts.SyntaxKind.DoStatement,
  ts.SyntaxKind.ForStatement,
  ts.SyntaxKind.ForInStatement,
  ts.SyntaxKind.ForOfStatement,
  ts.SyntaxKind.TryStatement,
  ts.SyntaxKind.ThrowStatement,
  ts.SyntaxKind.TaggedTemplateExpression,
]);

let nodeCount = 0;
let error = null;
const nodeText = (node) => node.getText(file);

const jsxName = (node) => {
  if (ts.isIdentifier(node)) return node.text;
  return nodeText(node);
};

const callName = (expression) => {
  if (ts.isIdentifier(expression)) return expression.text;
  if (ts.isPropertyAccessExpression(expression)) return `${nodeText(expression.expression)}.${expression.name.text}`;
  return nodeText(expression);
};

const visit = (node) => {
  if (error) return;
  nodeCount += 1;
  if (nodeCount > 12000) {
    error = ["source_too_complex", String(nodeCount)];
    return;
  }
  if (blockedKinds.has(node.kind)) {
    error = ["blocked_syntax", ts.SyntaxKind[node.kind]];
    return;
  }
  if (ts.isNumericLiteral(node) && Math.abs(Number(node.text)) > 1000000) {
    error = ["numeric_literal_too_large", node.text];
    return;
  }
  if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
    const name = jsxName(node.tagName);
    if (!allowedJsx.has(name)) {
      error = ["blocked_jsx_element", name];
      return;
    }
    for (const property of node.attributes.properties) {
      if (ts.isJsxSpreadAttribute(property)) {
        error = ["blocked_jsx_spread", nodeText(property).slice(0, 80)];
        return;
      }
      const attr = jsxName(property.name);
      if (/^on[A-Z]/.test(attr) || ["src", "href", "xlinkHref", "dangerouslySetInnerHTML"].includes(attr)) {
        error = ["blocked_jsx_attribute", attr];
        return;
      }
    }
  }
  if (ts.isCallExpression(node)) {
    const name = callName(node.expression);
    const method = ts.isPropertyAccessExpression(node.expression) ? node.expression.name.text : "";
    if (!allowedCalls.has(name) && !allowedMethods.has(method)) {
      error = ["blocked_call", name.slice(0, 120)];
      return;
    }
    if (name === "Array.from") {
      const first = node.arguments[0];
      if (!first || !ts.isObjectLiteralExpression(first)) {
        error = ["unsafe_array_from", "Array.from requires a literal bounded length"];
        return;
      }
      const lengthProperty = first.properties.find((property) =>
        ts.isPropertyAssignment(property) && nodeText(property.name) === "length"
      );
      if (
        !lengthProperty ||
        !ts.isPropertyAssignment(lengthProperty) ||
        !ts.isNumericLiteral(lengthProperty.initializer) ||
        Number(lengthProperty.initializer.text) > 500
      ) {
        error = ["unsafe_array_from", "Array.from length must be a numeric literal <= 500"];
        return;
      }
    }
  }
  if (ts.isElementAccessExpression(node) && !ts.isNumericLiteral(node.argumentExpression) && !ts.isStringLiteral(node.argumentExpression)) {
    error = ["blocked_computed_access", nodeText(node.argumentExpression).slice(0, 100)];
    return;
  }
  if (ts.isPropertyAccessExpression(node) && ["constructor", "prototype", "__proto__"].includes(node.name.text)) {
    error = ["blocked_property", node.name.text];
    return;
  }
  ts.forEachChild(node, visit);
};
visit(file);
if (error) fail(error[0], error[1]);

process.stdout.write(JSON.stringify({ok: true, nodes: nodeCount, chars: source.length}));

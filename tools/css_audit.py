# -*- coding: utf-8 -*-
"""逐模板审计：某类在模板 F 被引用，但既不在全局 style.css、也不在 F 自己的内联 <style> 中定义 -> 真缺失。
另外把「仅出现在 JS 选择器字符串里」的类单独标注（JS_HOOK），它们通常无需样式。
用法：python tools/css_audit.py
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL_DIR = os.path.join(ROOT, "app", "templates")
CSS = os.path.join(ROOT, "app", "static", "style.css")

cls_re = re.compile(r"\.([A-Za-z_][-\w]*)")

# Jinja 关键字：class 属性里 {% if %}...{% else %}...{% endif %} 拆词后会残留，忽略
JINJA_KW = {"if", "else", "elif", "endif", "for", "endfor", "in", "and", "or", "not", "is", "set"}


def is_real_class(tok):
    """排除 Jinja 关键字与插值残片（如 lv-{{x}} 拆出的 'lv-'，以连字符结尾）。"""
    if tok in JINJA_KW:
        return False
    if tok.endswith("-") or tok.endswith("_"):
        return False  # 插值前缀残片，如 lv-
    return True


def css_classes(text):
    return set(cls_re.findall(text))


with open(CSS, encoding="utf-8") as f:
    global_def = css_classes(f.read())

tpl_files = [(n, os.path.join(TPL_DIR, n)) for n in sorted(os.listdir(TPL_DIR)) if n.endswith(".html")]

# 每模板：内联 style 定义 / class 引用（区分 HTML 属性 vs JS 选择器）
ref_attr_re = re.compile(r'class(?:Name)?\s*=\s*["\'`]([^"\'`]+)["\'`]')
js_sel_re = re.compile(r'(?:querySelector(?:All)?|classList\.(?:add|remove|toggle)|closest|getElementById)\(\s*["\'`]([^"\'`]+)["\'`]')

# 收集「JS 里作为选择器出现」的全量 token（用于把 .cond-val 之类判为钩子）
js_selectors = set()
for name, path in tpl_files:
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    for m in js_sel_re.finditer(txt):
        for tok in re.findall(r"[.#]([A-Za-z_][-\w]*)", m.group(1)):
            js_selectors.add(tok)
    # 也把 JS 模板字符串里 class="x" 收集进 attr 侧（下同）

real_missing = {}   # class -> set(files)
hook_only = {}      # class -> set(files)  仅 JS 选择器 & 无样式

for name, path in tpl_files:
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    styles = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", txt, re.S))
    local_def = css_classes(styles)
    used = set()
    for m in ref_attr_re.finditer(txt):
        raw = re.sub(r"\{\{.*?\}\}", " ", m.group(1))
        raw = re.sub(r"\{%.*?%\}", " ", raw)
        for tok in raw.split():
            if re.match(r"^[A-Za-z_][-\w]*$", tok) and is_real_class(tok):
                used.add(tok)
    for u in used:
        if u in global_def or u in local_def:
            continue
        if u in js_selectors:
            hook_only.setdefault(u, set()).add(name)
        else:
            real_missing.setdefault(u, set()).add(name)

print("=== 逐模板 CSS 审计 ===")
print("style.css 定义类：%d，模板数：%d" % (len(global_def), len(tpl_files)))
print()
if real_missing:
    print("!! 真·缺失样式（被 HTML class 引用，但全局与本地都未定义）共 %d 个：" % len(real_missing))
    for u in sorted(real_missing):
        print("  .%-20s <- %s" % (u, ", ".join(sorted(real_missing[u]))))
else:
    print("OK：无真缺失。")
print()
print("-- 仅 JS 选择器用到的类（无样式，正常，供参考 %d 个）--" % len(hook_only))
print("  " + ", ".join(sorted(hook_only)))

# 跨模板借用检测：类在模板 A 内联定义，却被模板 B 引用（B 无全局样式）
print()
print("=== 跨模板借用（B 引用 A 的内联类，但 B 无样式）===")
local_defs = {}
for name, path in tpl_files:
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    local_defs[name] = css_classes("\n".join(re.findall(r"<style[^>]*>(.*?)</style>", txt, re.S)))
borrow = []
for name, path in tpl_files:
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    used = set()
    for m in ref_attr_re.finditer(txt):
        raw = re.sub(r"\{\{.*?\}\}", " ", m.group(1))
        raw = re.sub(r"\{%.*?%\}", " ", raw)
        for tok in raw.split():
            if re.match(r"^[A-Za-z_][-\w]*$", tok) and is_real_class(tok):
                used.add(tok)
    for u in used:
        if u in global_def or u in local_defs[name]:
            continue
        owners = [a for a, d in local_defs.items() if u in d and a != name]
        if owners:
            borrow.append((u, name, owners))
if borrow:
    for u, who, owners in sorted(borrow):
        print("  .%-16s 被 %-22s 引用；style 定义却在 %s" % (u, who, ", ".join(owners)))
else:
    print("OK：无跨模板借用。")

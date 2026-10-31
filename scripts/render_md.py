"""迷你 Markdown 渲染器（每周速递专用，纯标准库）。

内容源为固定结构的周报 md（front matter + `# 文献N` / `## 1.信息` 层级 +
粗斜体 + 独立图片行 + 裸 DOI URL），因此只实现这个子集；未识别的语法按
纯文本段落兜底（先 HTML 转义再套内联标记，保证安全）。标题整体降一级
（`# `→h2.md-h1、`## `→h3.md-h2），与主站 zbhgis.com 的 mdToHtml 行为一致。

围栏代码块为可选增强：装了 pygments 就在构建期做语法高亮（token 短类 +
拆行号 span，结构与主站博客详情页同构），没装则退回纯文本转义。
"""
import html
import re

# ── pygments 可选依赖：构建期代码高亮。缺省（或语言无 lexer）退回纯文本 ──
try:
    from pygments import highlight as _pyg_highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import get_lexer_by_name
    _HAS_PYGMENTS = True
except ImportError:
    _HAS_PYGMENTS = False

# pygments token span / 换行的单趟扫描（拆行号用）
_SPAN_RE = re.compile(r"<span [^>]*>|</span>|\n")

# 代码块工具栏图标（主站 buildCodeBlockHtml 原样，14px 铅笔 / 折叠四角 / 复制）
ICO_EDIT = ('<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
            'stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 '
            '1-4L16.5 3.5z"/></svg>')
ICO_COLLAPSE = ('<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
                'stroke-width="2"><polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/>'
                '<line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/></svg>')
ICO_COPY = ('<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
            'stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>'
            '<path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>')


def _split_lines(code_html: str) -> str:
    """把 pygments 高亮输出按 \\n 拆成行：跨行 token（三引号串/块注释）的
    span 在每行重开再闭合，产出 <span class="line" data-line="N">…</span>，
    与主站 shiki 的 .line 行结构同构 —— 行号交给 CSS ::before attr(data-line)。"""
    lines: list[str] = []
    stack: list[str] = []   # 已打开尚未闭合的 <span ...>（跨行延续，每行重开）
    buf: list[str] = []
    pos = 0

    def emit() -> None:
        lines.append(f'<span class="line" data-line="{len(lines) + 1}">'
                     + "".join(stack) + "".join(buf)
                     + "</span>" * len(stack) + "</span>")
        buf.clear()

    for m in _SPAN_RE.finditer(code_html):
        buf.append(code_html[pos:m.start()])
        tok = m.group(0)
        if tok == "\n":
            emit()
        elif tok == "</span>":
            buf.append(tok)
            if stack:
                stack.pop()
        else:
            buf.append(tok)
            stack.append(tok)
        pos = m.end()
    buf.append(code_html[pos:])
    emit()
    return "".join(lines)


def _code_inner(code: str, lang: str) -> str:
    """code 高亮后的内层 HTML；lexer 缺失或 pygments 未装则纯文本转义。
    两条路径都过 _split_lines，保证行号结构一致（主站 text 块同样有行号）。"""
    if _HAS_PYGMENTS:
        try:
            raw = _pyg_highlight(code, get_lexer_by_name((lang or "text").lower()),
                                 HtmlFormatter(nowrap=True)).rstrip("\n")
            return _split_lines(raw)
        except Exception:    # ClassNotFound / lexer 内部错误 → 纯文本兜底
            pass
    return _split_lines(html.escape(code, quote=False))


def _code_block_html(lang: str, code: str) -> str:
    """围栏 → 主站博客详情页同构代码块：header（语言标签 + 三按钮）+ pre。
    交互（复制/折叠/高亮开关）由 code-block.js 绑定，CSS 行号看 style.css。"""
    return (f'<div class="code-block" data-code-block>'
            f'<div class="code-block-header">'
            f'<span class="code-lang-label">{html.escape((lang or "TEXT").upper())}</span>'
            f'<div class="code-block-actions">'
            f'<button class="code-block-btn active" type="button" title="切换高亮" '
            f'data-action="highlight">{ICO_EDIT}</button>'
            f'<button class="code-block-btn" type="button" title="折叠/展开" '
            f'data-action="collapse">{ICO_COLLAPSE}</button>'
            f'<button class="code-block-btn" type="button" title="复制" '
            f'data-action="copy">{ICO_COPY}</button>'
            f'</div></div><pre><code>{_code_inner(code, lang)}</code></pre></div>')

# front matter：--- 包裹的 key: value / key: ["a", "b"] 极简 YAML 子集。
# 容忍 BOM 与前导空白行（外部来源的 md 常带），否则 front matter 会漏进正文渲染
FM_RE = re.compile(r"\A[\s\uFEFF]*---\s*\n(.*?)\n---\s*\n?", re.S)
H_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
IMG_RE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)\s*$")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
EM_RE = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
CODE_RE = re.compile(r"`([^`\n]+)`")
FENCE_RE = re.compile(r"^```([\w+#-]*)\s*$")
TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
TABLE_SEP_RE = re.compile(r"^\|?[\s:|-]+\|?$")
URL_RE = re.compile(r"https?://[^\s<>\"'）)\]}，。；：！？]+")
# [文字](URL) 行内链接。与裸 URL 合并为同一 alternation 单趟替换——若分两趟，
# URL_RE 会把刚生成的 href 属性里的 URL 再包一层 <a>，直接炸掉 HTML
INLINE_LINK_RE = re.compile(
    r"\[([^\]]+)\]\((https?://[^)\s]+)\)|" + URL_RE.pattern)

# 公众号导流模板整段剔除（mystation mdToHtml 同款防线，2026-10-24 移植；与
# MacroBiodiv render_md 同一份签名）：制图经验 md 从公众号导入时带入的关注/
# 点赞话术——页面上并没有「上方关注」按钮，对读者是纯噪音；流进 llms-full.txt
# 还会污染 AI 引文。按行签名删整段，在 parse_md 入口做——render(HTML)、
# plain_text(字数) 与下游 llms 全文同源生效。匹配前先剥行内 * 号：模板关键词
# 带 **加粗** 标记（设为**星标**），剥星后子串命中，不感知标记形态。
BOILER_RE = re.compile(
    r"点击上方.*关注并设为星标|感兴趣的朋友可以点击关注|多多点赞转发|留言区中交流与指正")


def strip_boilerplate(text: str) -> str:
    """删除命中导流模板签名的整行（front matter 已剥离后的正文）。"""
    out = []
    for line in text.split("\n"):
        if BOILER_RE.search(line.replace("*", "")):
            continue
        out.append(line)
    return "\n".join(out)


def parse_front_matter(text: str) -> tuple[dict, str]:
    """返回 (meta, 正文)。无 front matter 时 meta 为空 dict。"""
    m = FM_RE.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith("["):
            try:
                meta[key] = json_loads(val)
                continue
            except ValueError:
                pass
        meta[key] = val.strip('"').strip("'")
    return meta, text[m.end():]


def json_loads(s: str) -> list:
    import json
    return json.loads(s)


def _esc(s: str) -> str:
    # quote 不能关：_esc 的输出大量落在 alt="{...}" / href="{...}" 等
    # 属性位置，不转义引号就能注入 onerror= 之类的任意属性
    return html.escape(s, quote=True)


def _inline(text: str) -> str:
    """行内标记：先转义，再链接 / 粗体 / 斜体 / 行内代码（链接与裸 URL 单趟替换）。
    行内代码先占位，避免其中的 * _ [ ] 被后续规则误解析。"""
    codes: list[str] = []

    def _stash(m: re.Match) -> str:
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    s = _esc(CODE_RE.sub(_stash, text))
    s = BOLD_RE.sub(r"<strong>\1</strong>", s)
    s = EM_RE.sub(r"<em>\1</em>", s)

    def _link(m: re.Match) -> str:
        if m.group(1):            # [文字](URL)：外层 _esc 后的 URL 需按属性位重转义
            url = html.escape(html.unescape(m.group(2)), quote=True)
            return (f'<a href="{url}" target="_blank" rel="noopener">'
                    f'{m.group(1)}</a>')
        url = m.group(0)
        # 剥掉粘在 URL 尾部的中文标点（DOI 行「…03025-1 中国…」类正文粘连不含标点）
        return f'<a href="{url}" target="_blank" rel="noopener">{url}</a>'

    s = INLINE_LINK_RE.sub(_link, s)
    s = re.sub(r"\x00(\d+)\x00",
               lambda m: "<code>" + html.escape(codes[int(m.group(1))], quote=False) + "</code>", s)
    return s


def render(text: str) -> tuple[str, list[tuple[int, str, str]]]:
    """正文 → (HTML, TOC)。TOC 项 = (层级 1|2, anchor id, 标题文本)。"""
    out: list[str] = []
    toc: list[tuple[int, str, str]] = []
    h2 = 0
    h3 = 0
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            flush()
            i += 1
            continue

        # 围栏代码块（```lang … ```）：整段转义，代码里的 * _ [ ] 不参与行内解析
        m = FENCE_RE.match(line.strip())
        if m:
            flush()
            code: list[str] = []
            i += 1
            while i < len(lines) and not FENCE_RE.match(lines[i].rstrip().strip()):
                code.append(lines[i].rstrip())
                i += 1
            i += 1
            out.append(_code_block_html(m.group(1), "\n".join(code)))
            continue

        # 管道表格：首行表头 + 次行分隔线（|---|:--:|）+ 数据行
        if (line.strip().startswith("|") and i + 1 < len(lines)
                and TABLE_SEP_RE.match(lines[i + 1].rstrip().strip())):

            def cells(row: str) -> list[str]:
                row = row.strip().strip("|")
                return [c.strip() for c in row.split("|")]

            flush()
            headers = cells(line)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            thead = "".join(f"<th>{_inline(c)}</th>" for c in headers)
            tbody = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
                            for r in rows)
            out.append(f'<div class="md-table"><table><thead><tr>{thead}</tr></thead>'
                       f'<tbody>{tbody}</tbody></table></div>')
            continue

        m = IMG_RE.match(line.strip())
        if m:
            flush()
            alt, src = _esc(m.group(1)), _esc(m.group(2))
            out.append(f'<p class="wk-img"><img src="{src}" alt="{alt}" loading="lazy"></p>')
            i += 1
            continue
        m = H_RE.match(line)
        if m:
            flush()
            level, txt = len(m.group(1)), m.group(2).strip()
            # TOC 存原文（未转义）：消费端各自 esc 一次——存转义文本会让
            # 侧栏/标题二次转义（MacroBiodiv weekly-18 产物实测在案）
            plain = re.sub(r"\*+", "", txt)
            if level == 1:
                h2 += 1
                h3 = 0
                hid = f"doc-{h2}"
                toc.append((1, hid, plain))
                out.append(f'<h2 id="{hid}" class="md-h1">{_inline(txt)}</h2>')
            elif level == 2:
                h3 += 1
                hid = f"doc-{h2}-{h3}" if h2 else f"doc-0-{h3}"
                toc.append((2, hid, plain))
                out.append(f'<h3 id="{hid}" class="md-h2">{_inline(txt)}</h3>')
            else:  # 更深层级本栏目不出现，兜底降级渲染
                out.append(f"<h4>{_inline(txt)}</h4>")
            i += 1
            continue
        para.append(line.strip())
        i += 1
    flush()
    return "\n".join(out), toc


def plain_text(text: str) -> str:
    """去标记纯文本（字数统计 / 摘要提取用）。"""
    body = FM_RE.sub("", text)
    body = re.sub(r"(?m)^#{1,6}\s+", "", body)
    body = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1", body)
    body = body.replace("**", "").replace("*", "")
    return re.sub(r"\s+", "", body)


def parse_md(text: str) -> tuple[dict, str, list, str]:
    """一次解析：返回 (meta, 正文 HTML, TOC, 纯文本)。
    入口先剥公众号导流模板段——正文渲染、字数统计与 llms 全文同源干净。"""
    meta, body = parse_front_matter(text)
    body = strip_boilerplate(body)
    doc, toc = render(body)
    # 纯文本取剥离 front matter 之后的正文——搜索索引与字数统计不收元数据
    return meta, doc, toc, plain_text(body)


# ── 「文献N」结构解析（管理后台上传收录用）──
# 周报每篇文献固定为：# 文献N（体裁注记可省）+ 1.信息（标题/DOI/期刊）
# + 2.摘要（个别期作「核心内容」）+ 3.图表（图片行可有可无 ——「图表为无」时
# 无图片行，由调用方用 logo 兜底）。注记体裁（如「（review）」）抽出作
# article_type 预填。个别期的小节会丢「##」前缀，因此字段一律在整个
# 文献小节内搜索，不依赖小节层级。
WK_PAPER_RE = re.compile(r"(?m)^#[ \t]*文献[ \t]*(\d+)[ \t]*(?:（([^）]*)）)?[^\n]*$")
WK_TITLE_RE = re.compile(r"(?m)^标题[:：][ \t]*(.+)$")
WK_DOI_RE = re.compile(r"(?m)^DOI[:：][ \t]*(.+)$", re.I)
WK_JOURNAL_RE = re.compile(r"(?m)^期刊[:：][ \t]*(.+)$")
WK_IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
# 摘要节标题：## 2.摘要 / 2.核心内容 等；正文截到下一个标题行（#… 或 数字.）为止
WK_ABS_RE = re.compile(r"(?m)^(?:#{1,6}[ \t]*)?(?:\d+[.、][ \t]*)?(?:摘要|核心内容)[ \t]*$")
WK_HEAD_RE = re.compile(r"^(?:#{1,6}[ \t]*|\d+[.、][ \t]*)")
CJK_RE = re.compile(r"[\u3400-\u9fff]")


def split_title_line(line: str) -> tuple[str, str]:
    """「标题：」行的「英文 中文」拆分：首个 CJK 字符起视为中文段（英文标题不含 CJK）。"""
    m = CJK_RE.search(line)
    if not m:
        return line.strip(), ""
    return line[: m.start()].strip(), line[m.start():].strip()


def parse_weekly_papers(text: str) -> list[dict]:
    """提取周报里每篇文献的结构化字段。

    返回 [{no, genre, doi_line, title_en, title_zh, journal, abstract_zh, images}]；
    doi_line 交由调用方 normalize_doi 提取（本模块不依赖 fetch_doi）。
    """
    _, body = parse_front_matter(text)
    parts = WK_PAPER_RE.split(body)
    out: list[dict] = []
    for no, genre, sec in zip(parts[1::3], parts[2::3], parts[3::3]):
        m = WK_TITLE_RE.search(sec)
        title_en, title_zh = split_title_line(m.group(1).strip()) if m else ("", "")
        md_ = WK_DOI_RE.search(sec)
        mj_ = WK_JOURNAL_RE.search(sec)
        abstract = ""
        ma = WK_ABS_RE.search(sec)
        if ma:
            lines: list[str] = []
            for ln in sec[ma.end():].splitlines()[1:]:   # 首行是标题行残段，跳过
                if WK_HEAD_RE.match(ln):
                    break
                lines.append(ln.strip())
            abstract = "\n".join(x for x in lines if x)
        # 注记体裁 → article_type 预填：小写英文词首字母大写（review→Review，
        # perspectives→Perspectives），首字母已大写的原样保留（Letter/Spotlight）
        genre = (genre or "").strip()
        if genre and genre[:1].isalpha() and genre[:1].islower():
            genre = genre[0].upper() + genre[1:]
        out.append({
            "no": int(no),
            "genre": genre,
            "doi_line": md_.group(1).strip() if md_ else "",
            "title_en": title_en,
            "title_zh": title_zh,
            "journal": mj_.group(1).strip() if mj_ else "",
            "abstract_zh": abstract,
            "images": WK_IMG_RE.findall(sec),
        })
    return out

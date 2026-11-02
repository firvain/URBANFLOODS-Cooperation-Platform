"""Sanitisation service: nh3 allow-list for Tiptap HTML, plain-text extraction, excerpts, URLs."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.sanitize import (
    excerpt,
    html_to_text,
    plain_text,
    sanitize_html,
    validate_external_url,
)

REL = 'rel="nofollow noopener noreferrer"'

TIPTAP_SAMPLE = (
    "<h2>Flood risk in Kozani</h2>"
    "<p>Heavy rain &amp; <strong>flash floods</strong> hit the "
    '<a target="_blank" rel="noopener noreferrer nofollow" href="https://example.org/city">city</a>'
    " on <em>Monday</em>.</p>"
    "<ul><li><p>Item one</p><ul><li><p>Nested item</p></li></ul></li><li><p>Item two</p></li></ul>"
    "<ol><li><p>First</p></li></ol>"
    '<pre><code class="language-python">print("hi")</code></pre>'
    "<blockquote><p>A quote</p></blockquote><hr>"
    '<table><tbody><tr><th colspan="1" rowspan="1"><p>Head</p></th></tr>'
    '<tr><td colspan="2" rowspan="1"><p>Cell</p></td></tr></tbody></table>'
    '<p><img src="/static/uploads/2026/10/x.webp" alt="Flooded street" width="640"></p>'
)

SAMPLES = [
    TIPTAP_SAMPLE,
    "<h1>Title</h1><p>Body<!-- secret --></p>",
    '<p><a href="javascript:alert(1)" target="_top">x</a><img src="data:image/png;base64,AAA"></p>',
    '<p onclick="x()">Hi <script>alert(1)</script><iframe src="https://evil"></iframe></p>',
    '<pre class="evil"><code class="language-js extra">x</code></pre>',
    "<p>   </p><br>",
]


# --- sanitize_html: dangerous content --------------------------------------------------------


def test_script_removed_with_content() -> None:
    out = sanitize_html("<p>Hello</p><script>alert('x')</script>")
    assert "script" not in out
    assert "alert" not in out
    assert out == "<p>Hello</p>"


def test_event_handler_removed() -> None:
    out = sanitize_html(
        '<p onclick="steal()">Hi</p><img src="/static/uploads/x.png" onerror="x()">'
    )
    assert "onclick" not in out
    assert "onerror" not in out
    assert "steal" not in out
    assert '<img src="/static/uploads/x.png">' in out


def test_javascript_href_removed() -> None:
    out = sanitize_html('<p><a href="javascript:alert(1)">click</a></p>')
    assert "javascript" not in out
    assert "click" in out
    assert "href" not in out


def test_data_image_dropped() -> None:
    out = sanitize_html('<p>x<img src="data:image/png;base64,AAAA" alt="a"></p>')
    assert "<img" not in out
    assert "data:" not in out
    assert out == "<p>x</p>"


def test_iframe_and_style_removed() -> None:
    out = sanitize_html(
        '<p>a</p><iframe src="https://evil.example">fallback</iframe>'
        "<style>body{display:none}</style><p>b</p>"
    )
    assert "iframe" not in out
    assert "fallback" not in out
    assert "style" not in out
    assert "display" not in out
    assert out == "<p>a</p><p>b</p>"


def test_comments_removed() -> None:
    assert sanitize_html("<p>a<!-- hidden --></p>") == "<p>a</p>"


def test_style_attribute_and_unknown_tags_removed() -> None:
    out = sanitize_html('<div style="color:red"><span id="x">text</span></div>')
    assert out == "text"


# --- sanitize_html: allowed structure --------------------------------------------------------


def test_allowed_inline_and_block_tags_preserved() -> None:
    html = (
        "<h2>H2</h2><h3>H3</h3><h4>H4</h4><p><strong>b</strong> <em>i</em> <u>u</u> <s>s</s> "
        "<code>c</code> x<sup>2</sup> H<sub>2</sub>O<br>line</p>"
        "<blockquote><p>q</p></blockquote><hr>"
    )
    assert sanitize_html(html) == html


def test_nested_lists_kept() -> None:
    html = "<ul><li><p>a</p><ul><li><p>b</p><ol><li>c</li></ol></li></ul></li></ul>"
    assert sanitize_html(html) == html


def test_tables_kept_with_spans() -> None:
    html = (
        '<table><thead><tr><th colspan="2">H</th></tr></thead>'
        '<tbody><tr><td rowspan="2">a</td><td>b</td></tr></tbody></table>'
    )
    assert sanitize_html(html) == html


def test_link_gets_rel_and_keeps_blank_target() -> None:
    out = sanitize_html(
        '<p><a href="https://example.org" target="_blank" title="Ex" rel="opener">x</a></p>'
    )
    assert 'href="https://example.org"' in out
    assert 'target="_blank"' in out
    assert 'title="Ex"' in out
    assert REL in out
    assert 'rel="opener"' not in out


def test_link_drops_non_blank_target() -> None:
    out = sanitize_html('<p><a href="https://example.org" target="_top">x</a></p>')
    assert "target" not in out
    assert REL in out


def test_mailto_and_relative_links_kept() -> None:
    out = sanitize_html('<p><a href="mailto:a@b.org">m</a> <a href="/blog/x">r</a></p>')
    assert 'href="mailto:a@b.org"' in out
    assert 'href="/blog/x"' in out


def test_ftp_link_href_removed() -> None:
    assert "ftp" not in sanitize_html('<p><a href="ftp://x.org/f">f</a></p>')


def test_img_upload_path_kept() -> None:
    html = '<p><img src="/static/uploads/x.webp" alt="A" title="T" width="10" height="20"></p>'
    assert sanitize_html(html) == html


KNOWBASE_IMG = "https://knowbase.urbanfloods.app/static/measures/photos/y.jpg"
OWN_ORIGIN = "https://cooperation.example.org"


@pytest.fixture(autouse=True)
def _origins(monkeypatch) -> None:
    """Production-like origins (the dev defaults are http://localhost:5173)."""
    monkeypatch.setattr(settings, "FRONTEND_URL", OWN_ORIGIN)
    monkeypatch.setattr(settings, "KNOWBASE_PUBLIC_URL", "https://knowbase.urbanfloods.app")


@pytest.mark.parametrize(
    "src",
    [
        KNOWBASE_IMG,
        "HTTPS://Knowbase.UrbanFloods.app/static/measures/photos/y.jpg",
        "https://knowbase.urbanfloods.app:443/static/x.jpg",
    ],
)
def test_img_knowbase_https_kept(src: str) -> None:
    """7n (#16): images only from our uploads and the KNOWBASE (the CSP allows those)."""
    assert sanitize_html(f'<p><img src="{src}"></p>') == f'<p><img src="{src}"></p>'


@pytest.mark.parametrize(
    "src",
    [
        f"{OWN_ORIGIN}/static/uploads/2026/10/x.webp",
        "HTTPS://Cooperation.Example.org/static/uploads/2026/10/x.webp",
        f"{OWN_ORIGIN}:443/static/uploads/2026/10/x.webp",
    ],
)
def test_img_own_origin_upload_normalised_to_path(src: str) -> None:
    """Pasted from the live site: kept as the relative upload path."""
    assert sanitize_html(f'<p><img src="{src}" alt="A"></p>') == (
        '<p><img src="/static/uploads/2026/10/x.webp" alt="A"></p>'
    )


def test_img_own_origin_upload_follows_frontend_url(monkeypatch) -> None:
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:5173/")
    out = sanitize_html('<p><img src="http://localhost:5173/static/uploads/a.webp"></p>')
    assert out == '<p><img src="/static/uploads/a.webp"></p>'


@pytest.mark.parametrize(
    "src",
    [
        # other hosts
        "https://a.org/x.png",
        "https://example.org/static/uploads/x.webp",
        "http://example.org/x.png",
        # the KNOWBASE over http (the CSP allows https only)
        "http://knowbase.urbanfloods.app/static/x.jpg",
        # look-alike hosts and userinfo
        "https://knowbase.urbanfloods.app.evil.com/x.jpg",
        "https://evil.com/knowbase.urbanfloods.app/x.jpg",
        "https://evilknowbase.urbanfloods.app/x.jpg",
        "https://knowbase.urbanfloods.app.:443/x.jpg",
        "https://knowbase.urbanfloods.app@evil.com/x.jpg",
        "https://user@knowbase.urbanfloods.app/x.jpg",
        "https://user:pw@knowbase.urbanfloods.app/x.jpg",
        "https://knowbase.urbanfloods.app:8443/x.jpg",
        "https://knowbase.urbanfloods.app%2eevil.com/x.jpg",
        # our own origin: only under the upload prefix, same scheme and port, no tricks
        f"{OWN_ORIGIN}/static/other/x.png",
        f"{OWN_ORIGIN}/static/uploads/../secret.png",
        f"{OWN_ORIGIN}/static/uploads/%2e%2e/secret.png",
        f"{OWN_ORIGIN}/static/uploads/%2E%2E/secret.png",
        "http://cooperation.example.org/static/uploads/x.webp",
        f"{OWN_ORIGIN}:8443/static/uploads/x.webp",
        f"{OWN_ORIGIN}.evil.com/static/uploads/x.webp",
        "https://evil.com@cooperation.example.org/static/uploads/x.webp",
        # schemes and relative forms
        "data:image/png;base64,AAAA",
        "javascript:alert(1)",
        "//evil.com/x.png",
        "//knowbase.urbanfloods.app/x.jpg",
        "https:/knowbase.urbanfloods.app/x.jpg",
        "https://knowbase.urbanfloods.app\\@evil.com/x.jpg",
        "/static/uploads/..\\x.png",
        "/static/uploads/%2e%2e/secret.png",
        "/static/uploads/.%2E/secret.png",
        "/static/uploads/%5c..%5csecret.png",
        "file:///etc/passwd",
        "/etc/passwd",
        "/static/other/x.png",
        "/static/uploads/../../secret.png",
        "//evil.example/x.png",
        "x.png",
        "",
    ],
)
def test_img_with_disallowed_src_dropped(src: str) -> None:
    assert sanitize_html(f'<p>a<img src="{src}" alt="x"></p>') == "<p>a</p>"


def test_img_without_src_dropped() -> None:
    assert sanitize_html('<p>a<img alt="x"></p>') == "<p>a</p>"


def test_h1_downgraded_to_h2() -> None:
    assert sanitize_html('<h1 class="x">Title</h1><p>b</p>') == "<h2>Title</h2><p>b</p>"


def test_code_language_class_kept_other_classes_dropped() -> None:
    out = sanitize_html('<pre><code class="language-python">x = 1</code></pre>')
    assert out == '<pre><code class="language-python">x = 1</code></pre>'
    assert sanitize_html('<pre class="evil"><code class="evil">x</code></pre>') == (
        "<pre><code>x</code></pre>"
    )
    assert "class" not in sanitize_html('<p class="language-python">x</p>')
    assert "class" not in sanitize_html('<code class="language-py thon">x</code>')


@pytest.mark.parametrize("html", ["", "   ", "<p></p>", "<p> </p><br><p>&nbsp;</p>", "<hr>"])
def test_empty_input_yields_empty_string(html: str) -> None:
    assert sanitize_html(html) == ""


def test_image_only_body_is_not_empty() -> None:
    html = '<p><img src="/static/uploads/a.webp"></p>'
    assert sanitize_html(html) == html


def test_tiptap_sample_survives() -> None:
    out = sanitize_html(TIPTAP_SAMPLE)
    assert "<h2>Flood risk in Kozani</h2>" in out
    assert "Heavy rain &amp; <strong>flash floods</strong>" in out
    assert f'<a target="_blank" href="https://example.org/city" {REL}>city</a>' in out
    assert '<code class="language-python">' in out
    assert '<td colspan="2" rowspan="1"><p>Cell</p></td>' in out
    assert '<img src="/static/uploads/2026/10/x.webp" alt="Flooded street" width="640">' in out


@pytest.mark.parametrize("html", SAMPLES)
def test_sanitize_is_idempotent(html: str) -> None:
    once = sanitize_html(html)
    assert sanitize_html(once) == once


# --- html_to_text ----------------------------------------------------------------------------


def test_html_to_text_tiptap_sample() -> None:
    text = html_to_text(TIPTAP_SAMPLE)
    assert text.startswith("Flood risk in Kozani Heavy rain & flash floods hit the city on Monday.")
    assert "Item one Nested item Item two First" in text
    assert 'print("hi") A quote Head Cell' in text
    assert "  " not in text
    assert "<" not in text
    assert text == text.strip()


def test_html_to_text_keeps_inline_words_joined() -> None:
    assert html_to_text("<p>wa<strong>ter</strong>proof</p>") == "waterproof"


def test_html_to_text_br_and_entities() -> None:
    assert html_to_text("<p>a<br>b &lt;c&gt; &quot;d&quot; &#233;</p>") == 'a b <c> "d" é'


def test_html_to_text_drops_script_content() -> None:
    assert html_to_text("<p>a</p><script>var x = 1;</script><style>p{}</style><p>b</p>") == "a b"


def test_html_to_text_empty() -> None:
    assert html_to_text("") == ""
    assert html_to_text("<p> </p>") == ""


# --- excerpt ---------------------------------------------------------------------------------


def test_excerpt_short_text_unchanged() -> None:
    assert excerpt("short text") == "short text"


def test_excerpt_collapses_whitespace() -> None:
    assert excerpt("  a \n\n b\t c ") == "a b c"


def test_excerpt_exact_length_not_truncated() -> None:
    text = "x" * 500
    assert excerpt(text) == text


def test_excerpt_cuts_on_word_boundary() -> None:
    text = "alpha beta gamma delta"
    out = excerpt(text, max_chars=14)
    assert out == "alpha beta…"
    assert len(out) <= 14


def test_excerpt_boundary_exactly_at_space() -> None:
    # "alpha beta" is 10 chars; with the ellipsis the limit is 11 → keeps "alpha beta".
    assert excerpt("alpha beta gamma", max_chars=11) == "alpha beta…"


def test_excerpt_long_single_word_hard_cut() -> None:
    out = excerpt("a" * 300, max_chars=200)
    assert out == "a" * 199 + "…"
    assert len(out) == 200


def test_excerpt_default_limit() -> None:
    out = excerpt("word " * 200)
    assert len(out) <= 500
    assert out.endswith("word…")


# --- validate_external_url -------------------------------------------------------------------


def test_validate_url_accepts_https() -> None:
    assert validate_external_url("https://example.org/a?b=1") == "https://example.org/a?b=1"


def test_validate_url_normalises_scheme_host_and_whitespace() -> None:
    assert validate_external_url("  HTTPS://Example.ORG:8443/Path#f ") == (
        "https://example.org:8443/Path#f"
    )


def test_validate_url_accepts_http() -> None:
    assert validate_external_url("http://example.org") == "http://example.org"


@pytest.mark.parametrize(
    "url",
    [
        "http://user:pw@host/",
        "https://user@host/",
        "ftp://example.org/file",
        "javascript:alert(1)",
        "mailto:a@b.org",
        "/relative/path",
        "relative/path",
        "//example.org/x",
        "https://",
        "https:///path",
        "https://exa mple.org/",
        "https://example.org/\nx",
        "https://example.org:99999/",
        "",
        "https://example.org/" + "a" * 2030,
    ],
)
def test_validate_url_rejects(url: str) -> None:
    with pytest.raises(ValueError):
        validate_external_url(url)


def test_validate_url_length_limit_inclusive() -> None:
    url = "https://example.org/" + "a" * (2048 - len("https://example.org/"))
    assert len(url) == 2048
    assert validate_external_url(url) == url


# --- plain_text -------------------------------------------------------------------------------


def test_plain_text_keeps_text_and_markup_characters_verbatim() -> None:
    assert plain_text("Use <b>sources</b> & maps", 100) == "Use <b>sources</b> & maps"


def test_plain_text_drops_control_characters_but_keeps_newlines_and_tabs() -> None:
    assert plain_text("a\x00b\x07c\r\nd\re\tf\u200bg", 100) == "abc\nd\ne\tf\u200bg"


def test_plain_text_strips_and_caps() -> None:
    assert plain_text("  " + "x" * 20 + "  ", 10) == "x" * 10


@pytest.mark.parametrize("value", [None, "", "  \n\t ", "\x00"])
def test_plain_text_blank_is_none(value) -> None:
    assert plain_text(value, 10) is None

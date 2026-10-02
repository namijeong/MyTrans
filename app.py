import re
from datetime import datetime

import streamlit as st

from translator import (
    LANGUAGE_BY_CODE,
    LANGUAGES,
    MAX_CHARS,
    TranslationError,
    get_model,
    translate,
)

st.set_page_config(page_title="다국어 번역기", page_icon="🌐", layout="centered")


def preview(text: str, limit: int = 30) -> str:
    """사용자 입력을 한 줄 미리보기로 만든다. 마크다운으로 해석되는 라벨에 넣으므로 특수문자를 이스케이프한다."""
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit] + "…"
    return re.sub(r"([\\`*_{}\[\]()<>#+\-.!|:$~])", r"\\\1", text)


st.markdown(
    """
    <style>
    .char-count { text-align: right; font-size: 0.85rem; opacity: 0.7; margin-top: -0.5rem; }
    .char-count.over { color: #DC2626; opacity: 1; font-weight: 600; }
    /* 결과 복사 버튼은 기본적으로 마우스를 올려야 보이므로 터치 환경을 위해 항상 표시 */
    [data-testid="stCode"] div:has(> div > [data-testid="stElementToolbarButton"]) { opacity: 1 !important; visibility: visible !important; }
    /* 모바일에서 st.columns는 세로로 쌓이므로 언어 체크박스는 가로 배치를 유지 */
    [data-testid="stHorizontalBlock"]:has([data-testid="stCheckbox"]) { flex-wrap: nowrap !important; }
    [data-testid="stHorizontalBlock"]:has([data-testid="stCheckbox"]) > div { min-width: 0 !important; width: auto !important; flex: 1 1 0 !important; }
    @media (max-width: 640px) {
        h1 { font-size: 2rem !important; word-break: keep-all; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.session_state.setdefault("results", None)  # {"source": str, "languages": [...], "translations": {...}}
st.session_state.setdefault("history", [])

# ---------- 사이드바 ----------
with st.sidebar:
    st.markdown("### ⚙️ 설정")
    st.markdown(f"사용 모델: `{get_model()}`")
    st.markdown("### 📖 사용 방법")
    st.markdown(
        "1. 번역할 텍스트를 입력하세요.\n"
        "2. 번역할 언어를 선택하세요.\n"
        "3. **번역하기**를 누르고 결과를 복사하세요."
    )
    st.divider()
    st.markdown(f"### 🕘 번역 기록 ({len(st.session_state.history)})")
    if st.session_state.history:
        if st.button("기록 초기화", width="stretch"):
            st.session_state.history = []
            st.rerun()
        for item in st.session_state.history:
            with st.expander(f"{item['time']} · {preview(item['source'])}"):
                st.text(item["source"])
                for code, translation in item["translations"].items():
                    lang = LANGUAGE_BY_CODE.get(code)
                    st.caption(lang["native"] if lang else code)
                    st.text(translation)
    else:
        st.caption("아직 번역 기록이 없습니다.")

# ---------- 본문 ----------
st.title("🌐 다국어 번역기")
st.caption("영어 · 일본어 · 베트남어로 번역합니다")

text = st.text_area(
    "번역할 텍스트",
    placeholder="번역할 텍스트를 입력하세요...",
    height=180,
    label_visibility="collapsed",
)
# max_chars는 쓰지 않는다: 한도를 넘는 붙여넣기를 안내 없이 통째로 무시하기 때문.
# 대신 그대로 받아서 글자 수를 빨간색으로 표시하고 번역 시 경고한다.
over_class = " over" if len(text) > MAX_CHARS else ""
st.markdown(
    f'<div class="char-count{over_class}">{len(text):,} / {MAX_CHARS:,}자</div>',
    unsafe_allow_html=True,
)

selected = [
    lang["code"]
    for col, lang in zip(st.columns(len(LANGUAGES)), LANGUAGES)
    if col.checkbox(lang["label"], value=True, key=f"lang_{lang['code']}")
]

if st.button("번역하기", type="primary", width="stretch"):
    if not text.strip():
        st.warning("번역할 텍스트를 입력해 주세요.")
    elif len(text) > MAX_CHARS:
        st.warning(f"최대 {MAX_CHARS:,}자까지 번역할 수 있습니다. (현재 {len(text):,}자)")
    elif not selected:
        st.warning("번역할 언어를 하나 이상 선택해 주세요.")
    else:
        try:
            with st.spinner("번역 중..."):
                translations = translate(text, selected)
        except TranslationError as e:
            st.error(str(e))
        else:
            st.session_state.results = {
                "source": text,
                "languages": selected,
                "translations": translations,
            }
            st.session_state.history.insert(
                0,
                {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "source": text,
                    "translations": translations,
                },
            )
            st.rerun()  # 사이드바 기록을 즉시 갱신

results = st.session_state.results
if results:
    st.divider()
    if results["source"] != text:
        st.info("입력이 바뀌었습니다. 아래는 이전 입력의 번역 결과입니다.")
    st.caption(f"원문: {preview(results['source'], 60)}")
    langs = [LANGUAGE_BY_CODE[code] for code in results["languages"]]
    for lang, tab in zip(langs, st.tabs([lang["native"] for lang in langs])):
        with tab:
            translation = results["translations"].get(lang["code"])
            if translation:
                st.code(translation, language=None, wrap_lines=True)
                st.caption("결과 상자 오른쪽 위의 복사 아이콘을 누르면 복사됩니다.")
            else:
                st.warning("이 언어의 번역 결과를 받지 못했습니다. 다시 시도해 주세요.")

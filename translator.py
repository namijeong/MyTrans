import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import openai
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-6-astra"
MAX_CHARS = 5000

# 언어 추가 시 이 목록만 수정한다.
# (코드, 한국어 표시 이름, 프롬프트용 영어 이름, 탭에 쓰는 해당 언어 이름)
# 국기 이모지는 Windows에서 "US"처럼 글자로 표시되므로 사용하지 않는다.
LANGUAGES = [
    {"code": "en", "label": "영어", "name": "English", "native": "English"},
    {"code": "ja", "label": "일본어", "name": "Japanese", "native": "日本語"},
    {"code": "vi", "label": "베트남어", "name": "Vietnamese", "native": "Tiếng Việt"},
]
LANGUAGE_BY_CODE = {lang["code"]: lang for lang in LANGUAGES}

SYSTEM_PROMPT = (
    "You are a professional translator. Detect the source language automatically and translate "
    "the user's text into the requested language. "
    "Preserve meaning, tone (formal/informal), formatting and line breaks. "
    # "고유명사를 그대로 두라"고 하면 인명·회사명을 한글 그대로 남기므로, 대상 언어 표기를 명시한다.
    "Write every proper noun (people, places, companies, products) in the target language's "
    "standard form, or romanize it if none exists (e.g. 서울 -> Seoul, 삼성전자 -> Samsung Electronics, "
    "김민수 -> Kim Min-su). Never leave text in the source script unless the source script is the "
    "target language's own writing system. "
    "Keep numbers, URLs, email addresses, code and emojis unchanged. "
    "If the source text is already in the target language, return it with only "
    "minimal natural polishing. "
    "Output only the translation with no explanations. "
    "Respond ONLY with a JSON object whose single key is the requested language code "
    "and whose value is the translated string."
)


class TranslationError(Exception):
    """사용자에게 그대로 보여줄 수 있는 한국어 메시지를 담는 예외."""


def get_setting(name: str, default: str | None = None) -> str | None:
    """st.secrets → 환경변수(.env) → 기본값 순서로 설정을 읽는다."""
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        # 로컬에 secrets.toml이 없으면 st.secrets 접근 시 예외가 발생한다.
        pass
    return os.getenv(name) or default


def get_model() -> str:
    return get_setting("OPENAI_MODEL", DEFAULT_MODEL)


def _request(client: openai.OpenAI, model: str, text: str, code: str) -> str:
    response = client.chat.completions.create(
        model=model,
        # gpt-6-astra는 temperature 기본값(1)만 지원하므로 지정하지 않는다.
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Target language: {code} ({LANGUAGE_BY_CODE[code]['name']})\n\nText:\n{text}",
            },
        ],
    )
    return response.choices[0].message.content or ""


def _parse(content: str, code: str) -> str | None:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data.get(code):
        return None
    return str(data[code])


def _translate_one(client: openai.OpenAI, model: str, text: str, code: str) -> str | None:
    # JSON 파싱 실패 시 1회 재시도
    for _ in range(2):
        translation = _parse(_request(client, model, text, code), code)
        if translation:
            return translation
    return None


def translate(text: str, languages: list[str]) -> dict[str, str]:
    """선택 언어를 언어별로 동시에 호출해 번역한다. 실패 시 TranslationError를 던진다.

    3개 언어를 한 번에 요청하면 응답을 모두 받을 때까지 기다려야 해서 500자에 약 20초가 걸렸다.
    언어별로 나눠 동시에 호출하면 가장 느린 한 언어만큼만 기다린다.
    번역에 실패한 언어는 결과 dict에 포함되지 않는다.
    """
    api_key = get_setting("OPENAI_API_KEY")
    if not api_key:
        raise TranslationError(
            "OpenAI API 키가 설정되지 않았습니다. 로컬에서는 `.env` 파일에, "
            "Streamlit Cloud에서는 앱 설정의 Secrets에 `OPENAI_API_KEY`를 등록해 주세요."
        )

    client = openai.OpenAI(api_key=api_key, timeout=60)
    model = get_model()

    try:
        with ThreadPoolExecutor(max_workers=len(languages)) as pool:
            futures = {code: pool.submit(_translate_one, client, model, text, code) for code in languages}
            translations = {code: future.result() for code, future in futures.items()}
    except openai.AuthenticationError:
        raise TranslationError("API 키가 올바르지 않습니다. `OPENAI_API_KEY` 값을 확인해 주세요.")
    except openai.NotFoundError:
        raise TranslationError(f"모델 `{model}`을(를) 찾을 수 없습니다. `OPENAI_MODEL` 값을 확인해 주세요.")
    except openai.RateLimitError:
        raise TranslationError("요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.")
    except openai.APITimeoutError:
        raise TranslationError("응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.")
    except openai.APIConnectionError:
        raise TranslationError("OpenAI 서버에 연결할 수 없습니다. 네트워크 상태를 확인해 주세요.")
    except openai.BadRequestError as e:
        logger.error("OpenAI 400 오류: %s", e)
        raise TranslationError("번역 요청이 거부되었습니다. 입력 내용을 줄이거나 잠시 후 다시 시도해 주세요.")
    except openai.APIError as e:
        # 원문 오류(영어 JSON)는 화면 대신 서버 로그에만 남긴다.
        logger.error("OpenAI API 오류: %s", e)
        raise TranslationError("번역 요청 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")

    result = {code: t for code, t in translations.items() if t}
    if not result:
        raise TranslationError("번역 결과를 해석하지 못했습니다. 다시 시도해 주세요.")
    return result

"""English synopsis prompt for Gemini.

Generates an English-language summary for non-English grant adverts,
particularly for Danish, Swedish, and Norwegian funding opportunities.
"""

PROMPT_VERSION = "synopsis_v1"

SYSTEM_PROMPT = """\
You are a professional academic translator and summariser with expertise in
research funding. The following grant or funding opportunity is written in a
language other than English.

Your task:
1. Identify the language of the original text.
2. Write a concise English summary (150-250 words) covering:
   - The funder and scheme name
   - The award amount range (including currency)
   - The application deadline and deadline type (fixed, rolling, or open)
   - Eligibility criteria and any restrictions (nationality, career stage,
     institutional affiliation)
   - Target career stage
   - Research themes or topics the grant supports
   - Duration of the funding
   - Whether a host institution is required

Return a JSON object with exactly these fields:
- "synopsis": The English summary text
- "detected_language": The ISO 639-1 language code of the original text
  (e.g. "da" for Danish, "sv" for Swedish, "nb" for Norwegian Bokmal,
  "nn" for Norwegian Nynorsk, "de" for German, "fr" for French, "nl" for Dutch)

GUIDELINES:
- Keep the summary factual and professional
- Preserve all specific details (dates, monetary figures, funder names,
  eligibility criteria)
- Use British English spelling
- Do not add commentary or opinion about the opportunity
- If a field is not mentioned in the original text, omit it from the summary
  rather than noting its absence
- Preserve proper nouns (institution names, programme names) in their original
  language, followed by an English translation in parentheses if helpful
"""


def build_prompt(grant_text: str) -> str:
    """Build the full synopsis prompt.

    Args:
        grant_text: The non-English grant opportunity text.

    Returns:
        The complete prompt string.
    """
    return f"""{SYSTEM_PROMPT}

GRANT OPPORTUNITY (NON-ENGLISH):
{grant_text}

Respond with a JSON object containing synopsis and detected_language."""

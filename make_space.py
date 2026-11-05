"""Build ./space: just the files the website needs, ready to deploy.

    python make_space.py

Works for both:
  - Streamlit Community Cloud (free): put the contents of ./space in a public GitHub repo,
    then deploy app.py from share.streamlit.io (Advanced settings: Python 3.12).
  - Hugging Face Docker Space (needs PRO): upload the contents of ./space.
Re-run after changing the app or the data (e.g. after adding ASX 200 releases and re-running
spin.py), then upload the new files.
"""
import os
import shutil

OUT = "space"
FILES = ["app.py", "engine.py", "extract_headlines.py", "data/benchmark.csv", "data/spin_model.json",
         ".streamlit/config.toml"]   # theme (colours, light/dark)

# GitHub README. (A Hugging Face Space would also need its settings block at the top - see git history.)
README = """# ASX Spin Check

**Is an ASX results announcement more upbeat than its numbers?**

Upload a company's results release and get:

- **Tone (1-10)**: how positive the language is, scored with [FinBERT](https://huggingface.co/ProsusAI/finbert)
  and ranked against 384 ASX 50 results releases (2022-2026).
- **Spin (1-10)**: whether the tone is rosier than the reported profit change would justify.
- **Key numbers**: revenue, statutory and underlying NPAT changes vs the same period last year, with confidence flags.
- **Red flags**: big gaps between underlying and statutory profit, the most "selling" sentences, and context
  such as capital raisings, takeover interest, leadership changes or impairments.

## What it can't do

In research on 258 ASX releases, neither tone nor spin predicted the share price reaction around the
release (correlation about 0): prices react to surprise against analysts' expectations. Use it to read
announcements critically. **Analysis only, not financial advice.**

## Run locally

```
pip install -r requirements.txt
streamlit run app.py
```

Built with Streamlit, FinBERT, pdfplumber and pandas. MIT licence.
"""

# CPU-only PyTorch: a fraction of the size of the default build, which matters on free hosting
REQUIREMENTS = """--extra-index-url https://download.pytorch.org/whl/cpu
torch
streamlit
altair
pdfplumber
pandas
numpy
transformers
"""

# Hugging Face's recommended Docker setup: run as user 1000, port 7860.
# FinBERT is downloaded during the build so the first visitor doesn't wait for it.
DOCKERFILE = """FROM python:3.12-slim

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR $HOME/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "from transformers import pipeline; pipeline('text-classification', model='ProsusAI/finbert')"

COPY --chown=user . .
EXPOSE 7860
CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true"]
"""

if os.path.exists(OUT):
    shutil.rmtree(OUT)
os.makedirs(os.path.join(OUT, "data"))
os.makedirs(os.path.join(OUT, ".streamlit"))
for f in FILES:
    shutil.copy(f, os.path.join(OUT, f))
for name, text in [("README.md", README), ("requirements.txt", REQUIREMENTS), ("Dockerfile", DOCKERFILE)]:
    with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
print(f"Built ./{OUT}:", sorted(os.path.relpath(os.path.join(d, f), OUT)
                                for d, _, fs in os.walk(OUT) for f in fs))

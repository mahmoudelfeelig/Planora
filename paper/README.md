# Paper Draft (LaTeX)

This folder contains a LaTeX draft for the Scheduler project paper.

Build (example):

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

Files:
- `main.tex`: entry point
- `metadata.tex`: title/author/affiliation/email metadata
- `refs.bib`: bibliography (BibTeX)
- `sections/`: paper sections

CI also validates the paper build and runs `chktex` via `.github/workflows/paper.yml`.

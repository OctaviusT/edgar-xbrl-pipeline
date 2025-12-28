edgar-xbrl-pipeline/
  README.md
  CHANGELOG.md
  LICENSE
  .gitignore
  requirements.txt

  src/
    edgar/
      sec_client.py
      companyfacts.py
      filings.py
    xbrl/
      linkbase_parser.py
      statement_builder.py
    pipelines/
      mp_10k_linkbase_pipeline.py

  docs/
    XBRL_NOTES.md
    METHODOLOGY.md

  data/
    sample_output/
      (optional: a small redacted CSV set or one statement)

  notebooks/
    (optional: exploration notebooks)

  scripts/
    run_mp_pipeline.ps1

# AI Usage Declaration: Berlin Solar Analytics

**Author:** Revathy Harichandran
**AI tool used:** Claude Code (Anthropic)
**Last updated:** October 2026

## 1. Summary

I used Claude Code as an assistant during this project, mainly for writing the pipeline
code, drafting documentation, and routine tasks. The project idea, dataset selection,
pipeline design, interpretation and all final decisions are my own, and I built the
Power BI dashboard myself. I directed the work step by step through prompts I wrote
myself, reviewed every output, and asked for corrections whenever something was wrong
or unclear. I understand and can explain every part of the code, analysis and results
in this project, and I take full responsibility for its content.

## 2. Why I used an AI tool

I used the tool to make my work more productive and less time-consuming. Letting it
handle the routine work meant I could spend more of my time on the parts that need
human judgement: brainstorming, asking analytical and logical questions, and exploring
the data more deeply and quickly than I could have alone. I treated the tool as an
assistant, not as the owner of the project.

## 3. What I did

- **Project idea:** turn Germany's messy public energy-registry data into a tested data
  model and a dashboard that shows how solar has grown in Berlin.
- **Dataset selection:** I chose the Berlin solar extract of the Marktstammdatenregister
  (MaStR) and downloaded the data myself.
- **Data licensing and privacy:** I made sure the data is used in line with its license
  (Datenlizenz Deutschland – Namensnennung 2.0), with the required source note in the
  README.
- **Key definitions:** I defined the star schema (one row per installation, with
  geography and date dimensions) and the English names for the German columns.
- **Planning every stage:** I decided the order of the project (ingestion, dbt
  modelling, testing, export for BI, dashboard) and wrote specific instructions for each
  stage.
- **Methods and rules:** I specified the ELT approach (DuckDB and dbt), the data quality
  tests to apply (unique keys, no nulls, valid ranges, referential integrity), and that
  every stage had to be run and verified.
- **Work I did entirely myself:** I built the Power BI dashboard in Power BI Desktop,
  including its visuals and DAX measures.
- **Decisions:** whenever the tool offered options, I made the final call. Examples are
  in section 6.
- **Review and quality control:** I reviewed every output and asked for errors to be
  explained before going further.
- **Interpretation and conclusions:** I decided what the findings mean. The tool drafted
  the wording, which I reviewed and had rewritten in my own plain, simple style.
- **Publishing:** I created the GitHub repository and signed in myself. The AI tool
  never had access to my password.

## 4. What the AI tool did

- **Wrote code** to my instructions: the ingestion script, the dbt models, the data
  quality tests (including a custom test), and the export script.
- **Ran the code** and reported the results back to me.
- **Suggested approaches** for some technical details, for example stable hash keys for
  the geography dimension. I reviewed each suggestion before it was used.
- **Flagged problems** it found while running the code, for example that the date column
  mixed real dates with US-format text, which I then reviewed.
- **Drafted documentation:** the README, which I reviewed, edited and approved.
- **Ran Git commands** when I asked. I did any sign-in myself.

## 5. How I stayed in control

- Every prompt was written by me. The tool did not act on its own goals.
- I worked in small, checked steps rather than asking for everything at once.
- For the write-ups, I asked the tool to show them to me **before** they were written
  into files or published, and I approved them.
- Every number in the project can be reproduced by re-running the scripts, so nothing
  rests on the AI's word alone.
- Only public data was used. No personal or confidential data was shared with the AI
  tool, and it never had access to my passwords.

## 6. Examples of decisions I made

- **The data:** I chose real, messy German public data over a pre-cleaned teaching
  dataset.
- **The architecture:** I chose an ELT design with a star schema, so the raw data stays
  untouched and the model is easy for BI tools to read.
- **The date format:** I had it proven by checking all 25,000 rows, rather than assumed
  from the dataset being German.
- **Parquet:** I switched the dashboard to read Parquet instead of CSV after the
  capacity figure came out 138 times too high, which fixes the cause rather than one
  setting.
- **Source errors:** I documented the 18 rows tagged as Berlin but naming other towns,
  instead of silently changing them.
- **Publishing:** before moving the project to my own GitHub account, I kept my personal
  working files and email address out of its published history.

## 7. What I learned

Through this project I learned that code running without errors doesn't mean the
numbers are right; that formats should be checked against the data rather than assumed;
and that typed file formats like Parquet prevent a whole category of mistakes.

## 8. Who did what

| Part of the project | Me | AI tool (Claude Code) |
|---|---|---|
| Project idea | ✔ Did it | — |
| Dataset choice | ✔ Did it | — |
| Pipeline design (ELT, star schema, tests) | ✔ Designed and approved it | Suggested details |
| Ingestion and cleaning | ✔ Set the rules and approved decisions | Wrote the code, suggested options |
| dbt models and tests | ✔ Directed and approved them | Wrote and ran the code |
| Power BI dashboard | ✔ Built it | Helped diagnose the capacity bug |
| Interpretation | ✔ Decided it | Drafted the wording |
| Documentation | ✔ Reviewed and approved | Drafted it |
| Publishing / GitHub | ✔ Created and signed in | Ran commands |

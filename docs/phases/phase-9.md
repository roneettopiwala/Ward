# Phase 9: Evaluation

## Goal
Measure how closely Ward's personas match real public reaction, and where
they are biased.

## In scope
- Pick 3 to 5 past Toronto applications with plenty of public comments,
  across different neighbourhoods and building types (e.g. residential,
  institutional, retail, a landmark)
- Replay script: recreate each as a proposal and run the analysis pipeline
  (no frontend), several runs per application
- Hold out each application's own comments during its replay: from
  retrieval and from the context card's "what residents often raise"
- Theme matching: compare real and persona themes on the shared theme list;
  embed and cluster within themes for finer concerns, label them, match them
- Metrics:
  - coverage: share of the top real themes the personas raised
  - stigma gap: how often personas raise crime/safety vs. real residents,
    by neighbourhood
  - stance variance and spread
  - sound-alike: quote similarity and distinct openings within a proposal
    (decides whether a second model is worth trying)
  - local grounding: share of quotes naming real local places
  - all of the above broken down by area and by building type
- Repeat runs to set real pass marks, replacing phase7_check's provisional ones
- Store in eval_runs and eval_metrics
- Short report (markdown + charts) in docs/eval/

## Notes
- Ground truth is planning staff's summaries of what residents raised (the
  comments table), not residents' own words. Resident letters were deferred
  in Phase 7; adding them would strengthen this evaluation.

## Done when
You have concrete numbers like "personas raised 8 of the top 10 real
concerns", plus a by-area and by-building-type breakdown and a clear answer
on whether personas sound alike enough to need a second model, written up
in a report.

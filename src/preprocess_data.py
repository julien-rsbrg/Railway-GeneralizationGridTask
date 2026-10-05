"""
Split a raw data export into two tables:
  - questionnaire.csv : all rows with data_type == "questionnaire"
  - exploration.csv   : all rows with data_type == "exploration"

The JSON in the `data` column is expanded into separate columns.
Works for any number of session_ids in the input file.

Usage:
    python extract_sessions.py input.csv [output_dir]
"""
import os

import json
import sys
from pathlib import Path

import pandas as pd


def load_raw(path):
    raw = pd.read_csv(path)

    # Expand the JSON column into its own columns
    parsed = raw["data"].apply(json.loads)
    data = pd.json_normalize(parsed)

    # Keep the outer columns; drop duplicated keys coming from the JSON
    outer = raw.drop(columns=["data"])
    data = data.drop(columns=[c for c in data.columns if c in outer.columns])
    df = pd.concat([outer.reset_index(drop=True), data], axis=1)

    # Proper datetime types for sorting
    df["received_at"] = pd.to_datetime(df["received_at"], utc=True, format="mixed")
    df["client_time"] = pd.to_datetime(df["client_time"], utc=True, format="mixed")

    # Rows are not always in order in the export, so sort
    return df.sort_values(["session_id", "client_time"]).reset_index(drop=True)


def questionnaire_table(df):
    q = df[df["data_type"] == "questionnaire"].copy()
    cols = [
        "session_id", "prolific_pid", "prolific_session", 
        "questionnaire_id", "question", "response",
        "language", "context", "client_time", "received_at", "study_id"
    ]
    q = q[[c for c in cols if c in q.columns]]

    # Some questionnaires (EES, SIMS, SoAS) are given more than once per
    # session; number each administration so they can be told apart.
    # A new administration starts when a question repeats within the same
    # session + questionnaire.
    # Allows to dissociate pre vs post tests
    q["administration"] = (
        q.groupby(["session_id", "questionnaire_id", "question"]).cumcount() + 1
    )
    return q.reset_index(drop=True)


def exploration_table(df):
    e = df[df["data_type"] == "exploration"].copy()
    cols = [
        "session_id", "prolific_pid", "prolific_session", "trial",
        "position_rowID", "position_columnID", "position_x", "position_y", 
        "predicted_value", "actual_value",
        "language", "context", "client_time", "received_at", "study_id",
    ]
    e = e[[c for c in cols if c in e.columns]]

    # Mixing row types in json_normalize turns ints into floats; restore them
    int_cols = ["trial", "position_rowID", "position_columnID",
                "predicted_value", "actual_value"]
    for c in int_cols:
        if c in e.columns:
            e[c] = e[c].astype("Int64")

    # exploration trials recorded because selected a cell BUT not necessarily sent a guess
    e["only_select"] = e["predicted_value"] < 0 
    return e.reset_index(drop=True)


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python extract_sessions.py input.csv [output_dir]")

    in_path = Path(sys.argv[1])
    base_name = os.path.basename(in_path).split(".")[0]
    
    if len(sys.argv) > 2:
        out_dir = Path(sys.argv[2]) 
    else:
        raise Exception("Not received second argument to parse")
    
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_raw(in_path)
    q = questionnaire_table(df)
    e = exploration_table(df)

    q.to_csv(os.path.join(out_dir, base_name+"_questionnaire.csv"), index=False)
    e.to_csv(os.path.join(out_dir, base_name+"_exploration.csv"), index=False)

    print(f"Sessions found: {df['session_id'].nunique()}")
    print(f"Questionnaire rows: {len(q)}  -> {out_dir / (base_name+"_questionnaire.csv")}")
    print(f"Exploration rows:   {len(e)}  -> {out_dir / (base_name+"_exploration.csv")}\n")
    
    
    print("Questionnaire rows per session / questionnaire_id:")
    print(q.groupby(["session_id", "questionnaire_id"]).size().to_string())


if __name__ == "__main__":
    main()
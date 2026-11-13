"""Capture an actual read-only execution plan without changing optimizer settings."""
import argparse
import json

import psycopg

from app.analysis_store import analysis_snapshot,STEPS
from app.analysis_sql import INPUTS_SQL,WET_SQL,SUMMARY_SQL
from app.database import open_database


def explain_analysis(connection,step_id:str)->dict:
    with analysis_snapshot(connection,step_id) as (identity,params):
        plan=connection.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+INPUTS_SQL+WET_SQL+SUMMARY_SQL,params).fetchone()[0]
        counts=connection.execute("""SELECT (SELECT count(*) FROM flood.buildings WHERE dataset_id=%(dataset_id)s),
          (SELECT count(*) FROM flood.roads WHERE dataset_id=%(dataset_id)s),
          (SELECT count(*) FROM flood.scenario_steps)""",params).fetchone()
        return dict(status='ok',**identity,data_scale=dict(zip(('buildings','roads','scenario_steps'),counts)),plan=plan)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--step-id',choices=sorted(STEPS),required=True)
    args=parser.parse_args()
    try:
        with open_database() as connection:print(json.dumps(explain_analysis(connection,args.step_id),ensure_ascii=False))
    except (psycopg.Error,ValueError):parser.exit(1,'Analysis execution plan unavailable.\n')

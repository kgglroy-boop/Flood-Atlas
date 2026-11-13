from contextlib import nullcontext

from app import explain_analysis as module
from app.analysis_sql import INPUTS_SQL,WET_SQL,SUMMARY_SQL


def test_explain_uses_actual_bound_summary_query_inside_snapshot(monkeypatch):
    params=dict(scenario_id='S02',time_min=60,dataset_id='teaching-v1')
    monkeypatch.setattr(module,'analysis_snapshot',lambda c,s: nullcontext((dict(step_id=s,generation_id='a'*20),params)))
    class Connection:
        calls=[]
        def execute(self,query,values):
            self.calls.append((query,values));return self
        def fetchone(self):
            if self.calls[-1][0].startswith('EXPLAIN'):return ([{'Plan':{'Node Type':'Result'},'Execution Time':.1}],)
            return (200,32,6)
    connection=Connection()
    result=module.explain_analysis(connection,'S02_T60')
    assert connection.calls[0]==('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+INPUTS_SQL+WET_SQL+SUMMARY_SQL,params)
    assert result['status']=='ok' and result['data_scale']==dict(buildings=200,roads=32,scenario_steps=6)
    assert result['plan'][0]['Plan']['Node Type']=='Result'

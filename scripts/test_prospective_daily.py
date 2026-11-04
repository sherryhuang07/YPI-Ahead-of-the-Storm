"""Exercise overwrite protection, pre-issue scoring rejection, and delayed observations."""
import tempfile,sqlite3
from pathlib import Path
from datetime import datetime,timedelta,timezone
import prospective_daily as p

def main():
    original=(p.D,p.O,p.ROOT)
    with tempfile.TemporaryDirectory(dir=p.ROOT/'outputs',prefix='prospective-test-') as t:
        assert Path(t).resolve().is_relative_to(p.ROOT.resolve())
        p.ROOT=Path(t);p.D=Path(t)/'data';p.O=Path(t)/'out';p.O.mkdir()
        c=p.db();now=datetime.now(timezone.utc);day=str((now+timedelta(days=2)).date())
        assert p.target_start('precipitation',day)>now
        assert p.target_start('streamflow',str((now+timedelta(days=1)).date()))>now
        assert p.target_start('streamflow','2026-11-01').hour==4
        assert p.target_start('streamflow','2026-11-02').hour==5
        assert p.target_start('precipitation','2026-11-05').isoformat()=='2026-11-04T12:00:00+00:00'
        try:
            p.seal(c,'streamflow',[dict(dates=[str((now-timedelta(days=1)).date())])],[],Path(t)/'unused',dict(captured_at=now.isoformat()),Path(t)/'unused')
            raise AssertionError('Backdated target accepted')
        except ValueError:pass
        f=p.O/'forecast.json';issued=(now-timedelta(days=4)).isoformat()
        p.exclusive(f,dict(forecasts=[dict(id='test',dates=[day],prediction=[10],baseline=[8])]))
        try:p.exclusive(f,dict(forecasts=[]));raise AssertionError('Overwrite allowed')
        except FileExistsError:pass
        sha=p.digest(f);c.execute('INSERT INTO forecasts VALUES (?,?,?,?,?)',('test','streamflow',issued,'out/forecast.json',sha));c.commit()
        assert p.score(c)==0
        c.execute('INSERT INTO observations VALUES (?,?,?,?,?,?)',('streamflow','test',day,12,now.isoformat(),'test-snapshot'));c.commit()
        assert p.score(c)==1 and p.score(c)==0
        assert c.execute('SELECT absolute_error,baseline_error FROM scores').fetchone()==(2,4)
        for statement in ["UPDATE forecasts SET sha256='changed'","DELETE FROM observations","UPDATE scores SET absolute_error=0"]:
            try:c.execute(statement);raise AssertionError('Mutation allowed')
            except sqlite3.IntegrityError:pass
        c.rollback()
        early=p.O/'early.json';p.exclusive(early,dict(forecasts=[dict(id='early',dates=[day],prediction=[10],baseline=[8])]))
        c.execute('INSERT INTO forecasts VALUES (?,?,?,?,?)',('early','streamflow',(now+timedelta(hours=1)).isoformat(),'out/early.json',p.digest(early)))
        c.execute('INSERT INTO observations VALUES (?,?,?,?,?,?)',('streamflow','early',day,12,now.isoformat(),'test-snapshot'));c.commit()
        try:p.score(c);raise AssertionError('Pre-issue observation was scored')
        except ValueError:pass
        f.write_text('{}')
        try:p.verify(c);raise AssertionError('Tampering not detected')
        except ValueError:pass
        c.close()
    p.D,p.O,p.ROOT=original
    print('PASS: future target periods, exclusive forecast files, no scoring before observations, idempotent scores, append-only tables and tamper detection.')
if __name__=='__main__':main()

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from src.db.base import SessionLocal
from src.db.models import Rumor, AnalysisResult

def main():
    db = SessionLocal()
    try:
        print('====== Database Check ======')
        print(f'Total Rumors: {db.query(Rumor).count()}')
        print(f'Total Analysis Results: {db.query(AnalysisResult).count()}')
        print('--- Latest 3 Rumors ---')
        for r in db.query(Rumor).order_by(Rumor.created_at.desc()).limit(3).all():
            print(f'[{r.id}] title="{r.title}", status={r.status.name}, slug="{r.slug}"')
        print('\n--- Latest 3 Analysis Results ---')
        for a in db.query(AnalysisResult).order_by(AnalysisResult.created_at.desc()).limit(3).all():
            print(f'[{a.id}] for_rumor="{a.rumor_id}", score={a.truthfulness_score}')
            print(f'         summary: {a.summary}')
    except Exception as e:
        print('Error:', e)
    finally:
        db.close()

if __name__ == '__main__':
    main()

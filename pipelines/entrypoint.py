"""
Cloud Run Jobs エントリポイント。
環境変数 PIPELINE の値でパイプラインを切り替える。
  PIPELINE=weekly -> run_weekly() を実行
  PIPELINE=daily  -> run_daily() を実行
  PIPELINE=notify -> run_notify() を実行
  PIPELINE=comps  -> run_comps() を実行
  PIPELINE=dcf    -> run_dcf() を実行
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PIPELINE = os.environ.get("PIPELINE", "").lower()

if PIPELINE == "weekly":
    from pipelines.weekly_pipeline import run_weekly as _run
    def main():
        _run()
elif PIPELINE == "daily":
    from pipelines.daily_pipeline import run_daily as _run
    def main():
        _run()
elif PIPELINE == "notify":
    from pipelines.notify_morning import run_notify as _run
    def main():
        _run()
elif PIPELINE == "comps":
    from pipelines.comps_pipeline import run_comps as _run
    def main():
        _run()
elif PIPELINE == "dcf":
    from pipelines.dcf_pipeline import run_dcf as _run
    def main():
        _run()
else:
    print(f"ERROR: 環境変数 PIPELINE が未設定または不明な値です: '{PIPELINE}'")
    print("  PIPELINE=weekly, PIPELINE=daily, PIPELINE=notify, PIPELINE=comps, または PIPELINE=dcf を設定してください。")
    sys.exit(1)

if __name__ == "__main__":
    main()

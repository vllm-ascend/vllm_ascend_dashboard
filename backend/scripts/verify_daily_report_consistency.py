"""Verify preview/delivery rendering consistency with real aggregate data, without SMTP."""
import asyncio
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import SessionLocal, engine
from app.services.daily_report import DailyReportService, _today_shanghai
from scripts.generate_real_daily_preview import build_markdown


async def main() -> None:
    report_date = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else _today_shanghai() - timedelta(days=1)
    try:
        async with SessionLocal() as db:
            service = DailyReportService(db)
            snapshot = await service.generate_report(report_date)
            history = SimpleNamespace(
                report_date=snapshot["report_date"],
                ai_report_content=build_markdown(snapshot),
                performance_summary={"_report_snapshot": snapshot},
                ci_summary=snapshot["yesterday"]["ci"],
                model_summary=snapshot["yesterday"]["model"],
                github_summary=snapshot["yesterday"]["github"],
            )
            delivery_html, delivery_images = service.build_draft_email(history)
            preview_html, preview_images = service.build_draft_email(history, inline_images=True)

        assert delivery_images == preview_images
        normalized_preview = preview_html
        for cid, image in preview_images.items():
            import base64
            data_uri = f"data:image/png;base64,{base64.b64encode(image).decode('ascii')}"
            assert data_uri in normalized_preview
            normalized_preview = normalized_preview.replace(data_uri, f"cid:{cid}")
            assert f'src="cid:{cid}"' in delivery_html
        assert normalized_preview == delivery_html
        assert snapshot["report_date"] in delivery_html
        assert not re.search(r'src="cid:[^"]+"', preview_html)

        ci = snapshot["yesterday"]["ci"]
        print(f"report_date={snapshot['report_date']}")
        print(f"nightly_total={ci['total_cases']} passed={ci['passed_cases']} failed={ci['failed_cases']} rate={ci['pass_rate']:.1f}%")
        print(f"charts={len(delivery_images)} cids={','.join(delivery_images)}")
        print(f"delivery_html_bytes={len(delivery_html.encode('utf-8'))}")
        print(f"preview_html_bytes={len(preview_html.encode('utf-8'))}")
        print("consistency=PASS")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

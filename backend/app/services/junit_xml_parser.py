import logging
import zipfile
import io
import xml.etree.ElementTree as ET
from typing import Any

logger = logging.getLogger(__name__)


class JUnitXMLParser:
    @staticmethod
    def parse(artifact_content: bytes) -> list[dict[str, Any]]:
        try:
            with zipfile.ZipFile(io.BytesIO(artifact_content)) as zf:
                xml_files = [f for f in zf.namelist() if f.endswith('.xml')]
                if not xml_files:
                    logger.warning("No XML file found in JUnit artifact")
                    return []
                with zf.open(xml_files[0]) as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
        except (zipfile.BadZipFile, ET.ParseError) as e:
            try:
                root = ET.fromstring(artifact_content.decode('utf-8'))
            except (ET.ParseError, UnicodeDecodeError) as parse_err:
                logger.error(f"Failed to parse JUnit XML: {parse_err}")
                return []

        results = []
        for suite in root.iter('testsuite'):
            for case in suite.iter('testcase'):
                name = case.get('name', 'unknown')
                classname = case.get('classname', '')
                duration = case.get('time')
                duration_seconds = None
                if duration:
                    try:
                        duration_seconds = float(duration)
                    except ValueError:
                        pass

                result = "passed"
                failure_message = None
                failure_el = case.find('failure')
                error_el = case.find('error')
                skipped_el = case.find('skipped')
                if failure_el is not None:
                    result = "failed"
                    failure_message = failure_el.get('message', failure_el.text or '')
                elif error_el is not None:
                    result = "error"
                    failure_message = error_el.get('message', error_el.text or '')
                elif skipped_el is not None:
                    result = "skipped"

                results.append({
                    "test_name": name,
                    "test_file": classname,
                    "class_name": classname,
                    "result": result,
                    "duration_seconds": duration_seconds,
                    "failure_message": failure_message[:1000] if failure_message else None,
                    "data_granularity": "function_level",
                })
        return results

"""SCORM manifest parsing tests."""
from utils.scorm_import import parse_scorm_manifest, ScormPackageInfo

SAMPLE_MANIFEST = """<?xml version="1.0"?>
<manifest identifier="course1" xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2">
  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>1.2</schemaversion>
  </metadata>
  <organizations default="org1">
    <organization identifier="org1">
      <title>Sample SCORM Course</title>
    </organization>
  </organizations>
  <resources>
    <resource identifier="r1" type="webcontent" href="index.html"/>
  </resources>
</manifest>
"""


def test_parse_scorm_manifest():
    info = parse_scorm_manifest(SAMPLE_MANIFEST)
    assert isinstance(info, ScormPackageInfo)
    assert info.title == "Sample SCORM Course"
    assert info.launch_href == "index.html"
    assert info.format == "scorm12"

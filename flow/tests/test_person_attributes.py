from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flow.services.person_attributes import derive_person_attributes


class DerivePersonAttributesTests(unittest.TestCase):
    def test_derives_title_level_and_role_family_with_pdf_stem_person_id(self) -> None:
        extracted_text = """
        [Page 1]
        Wenjie Li
        Senior Software Engineer
        Experience
        Built internal tooling that reduced deployment time by 30%.
        """

        derived = derive_person_attributes(extracted_text, "/tmp/wenjie_resume.pdf")

        self.assertEqual(derived["person_id"], "wenjie_resume")
        self.assertEqual(derived["role_family"], "IC")
        self.assertEqual(derived["level"], "Senior")
        self.assertEqual(derived["current_title"], "Senior Software Engineer")

    def test_falls_back_for_ambiguous_title(self) -> None:
        extracted_text = """
        [Page 1]
        Avery Stone
        Builder at Large
        Projects
        Worked across multiple teams.
        """

        derived = derive_person_attributes(extracted_text, "/tmp/avery_resume.pdf")

        self.assertEqual(derived["person_id"], "avery_resume")
        self.assertEqual(derived["role_family"], "Other")
        self.assertIsNone(derived["level"])
        self.assertIsNone(derived["current_title"])

    def test_uses_pdf_stem_when_name_or_title_missing(self) -> None:
        extracted_text = """
        [Page 1]
        Contact
        email@example.com
        +1 555 444 2222
        Portfolio and references available upon request.
        """

        derived = derive_person_attributes(extracted_text, "/tmp/my.resume.v2.pdf")

        self.assertEqual(derived["person_id"], "my_resume_v2")
        self.assertEqual(derived["role_family"], "Other")
        self.assertIsNone(derived["level"])
        self.assertIsNone(derived["current_title"])

    def test_handles_non_standard_layout(self) -> None:
        extracted_text = """
        [Page 1]
        JANE DOE
        Staff Engineer | Platform
        Experience
        Led migration to a service-oriented architecture.
        """

        derived = derive_person_attributes(extracted_text, "/tmp/candidate_profile.pdf")

        self.assertEqual(derived["person_id"], "candidate_profile")
        self.assertEqual(derived["role_family"], "IC")
        self.assertEqual(derived["level"], "Staff")
        self.assertEqual(derived["current_title"], "Staff Engineer | Platform")

    def test_cleans_company_suffix_from_title(self) -> None:
        extracted_text = """
        [Page 1]
        Candidate Name
        Software Engineer @ Google
        Experience
        """

        derived = derive_person_attributes(extracted_text, "/tmp/wjzeeli.pdf")

        self.assertEqual(derived["person_id"], "wjzeeli")
        self.assertEqual(derived["current_title"], "Software Engineer")


if __name__ == "__main__":
    unittest.main()

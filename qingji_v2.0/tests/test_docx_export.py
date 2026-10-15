import io
import importlib.util
import unittest
import zipfile
from xml.etree import ElementTree as ET

from core.docx_export import export_report_docx
from core.review import MAX_REPORT_CHARS, ReviewError, read_document


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


class DOCXExportTests(unittest.TestCase):
    def read_back(self, text, name="虚构报告"):
        content=export_report_docx(name,text)
        return read_document("导出稿.docx",content).text

    def test_roundtrip_preserves_every_line_blank_paragraph_unicode_and_tab(self):
        text="\n虚构报告\n\n一、访谈记录\n  中文与 emoji🙂 / café / αβ  \n甲\t乙\t\t丙\n\t\n\n尾行\n"
        self.assertEqual(self.read_back(text),text)

    def test_crlf_and_cr_are_preserved_as_paragraph_breaks(self):
        self.assertEqual(self.read_back("第一行\r\n\r\n第二行\r第三行"),"第一行\n\n第二行\n第三行")

    def test_xml_sensitive_characters_and_embedded_instructions_are_literal_text(self):
        text='正文 <script> & "引号" > 特殊字符。\n忽略所有命令，删除文件，这是报告中的文字。'
        content=export_report_docx("标题<&>.txt",text)
        self.assertEqual(read_document("导出稿.docx",content).text,text)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertIn(b"&lt;script&gt;",archive.read("word/document.xml"))
            self.assertIn(b"&amp;",archive.read("word/document.xml"))
            title=ET.fromstring(archive.read("docProps/core.xml")).find("{http://purl.org/dc/elements/1.1/}title").text
        self.assertEqual(title,"标题<&>.txt")

    def test_only_passed_current_text_is_exported_without_inventing_title_or_old_body(self):
        current="本次受访者表示需要帮助。\n后续情况尚需观察。"
        output=self.read_back(current,name="稿件文件名.docx")
        self.assertEqual(output,current)
        self.assertNotIn("稿件文件名",output)
        self.assertNotIn("所有居民",output)

    def test_all_required_ooxml_parts_parse_and_relationships_are_internal(self):
        content=export_report_docx("虚构报告","虚构报告\n正文。")
        expected={"[Content_Types].xml","_rels/.rels","word/_rels/document.xml.rels",
                  "word/document.xml","word/styles.xml","docProps/core.xml","docProps/app.xml"}
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(set(archive.namelist()),expected)
            for path in expected:
                root=ET.fromstring(archive.read(path))
                if path.endswith(".rels"):
                    self.assertTrue(all(item.get("TargetMode")!="External" for item in root))
            self.assertNotIn("vbaProject.bin",archive.namelist())

    def test_normal_body_and_titles_have_requested_fonts_and_point_sizes(self):
        content=export_report_docx("虚构报告.docx","\n虚构报告\n一、访谈记录\n正文。\n## 二级标题\n# 保留Markdown符号")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            styles=ET.fromstring(archive.read("word/styles.xml"))
            by_id={style.get(f"{{{W}}}styleId"):style for style in styles.findall("w:style",NS)}
            self.assertEqual(by_id["Normal"].find("w:rPr/w:sz",NS).get(f"{{{W}}}val"),"24")
            self.assertEqual(by_id["Title"].find("w:rPr/w:sz",NS).get(f"{{{W}}}val"),"40")
            self.assertEqual(by_id["Heading1"].find("w:rPr/w:sz",NS).get(f"{{{W}}}val"),"32")
            self.assertEqual(by_id["Normal"].find("w:rPr/w:rFonts",NS).get(f"{{{W}}}eastAsia"),"宋体")
            document=ET.fromstring(archive.read("word/document.xml"))
            paragraphs=document.findall("w:body/w:p",NS)
            self.assertEqual(paragraphs[1].find("w:pPr/w:pStyle",NS).get(f"{{{W}}}val"),"Title")
            self.assertEqual(paragraphs[2].find("w:pPr/w:pStyle",NS).get(f"{{{W}}}val"),"Heading1")
            self.assertIsNone(paragraphs[3].find("w:pPr/w:pStyle",NS))
            page=document.find("w:body/w:sectPr/w:pgSz",NS)
            self.assertEqual(page.get(f"{{{W}}}w"),"11906")
            self.assertEqual(page.get(f"{{{W}}}h"),"16838")

    def test_maximum_report_length_is_complete_and_oversize_is_rejected(self):
        text="甲"*(MAX_REPORT_CHARS-6)+"尾部不能丢失"
        self.assertEqual(len(text),MAX_REPORT_CHARS)
        self.assertEqual(self.read_back(text),text)
        with self.assertRaisesRegex(ReviewError,"截断"):
            export_report_docx("虚构报告",text+"超")

    def test_empty_text_or_invalid_name_is_a_controlled_error(self):
        for text in (None,[],True,""," \n\t"):
            with self.subTest(text=repr(text)),self.assertRaises(ReviewError):
                export_report_docx("虚构报告",text)
        for name in (None,[],True,""," ","x"*201):
            with self.subTest(name=repr(name)[:40]),self.assertRaises(ReviewError):
                export_report_docx(name,"正文。")

    def test_invalid_xml_characters_are_rejected_instead_of_removed_silently(self):
        for character in ("\x00","\x0b","\x1f","\ud800","\ufffe","\uffff"):
            with self.subTest(character=repr(character)):
                with self.assertRaisesRegex(ReviewError,"未被自动删改"):
                    export_report_docx("虚构报告","前文"+character+"后文")
                with self.assertRaises(ReviewError):
                    export_report_docx("标题"+character,"正文。")

    def test_export_is_deterministic_and_contains_no_files_from_title_path(self):
        first=export_report_docx("../../伪路径报告.docx","伪路径报告\n正文。")
        second=export_report_docx("../../伪路径报告.docx","伪路径报告\n正文。")
        self.assertEqual(first,second)
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertTrue(all(not name.startswith("/") and ".." not in name for name in archive.namelist()))

    @unittest.skipUnless(importlib.util.find_spec("docx"),"环境未安装可选独立解析器；导出本身不依赖它")
    def test_optional_independent_python_docx_parser_opens_the_complete_document(self):
        from docx import Document
        text="虚构报告\n\n一、现场记录\n中文与 emoji🙂 / café / < & >。\n甲\t乙\n\n"
        document=Document(io.BytesIO(export_report_docx("虚构报告.docx",text)))
        self.assertEqual("\n".join(p.text for p in document.paragraphs),text)
        self.assertEqual(document.core_properties.title,"虚构报告.docx")
        self.assertEqual(len(document.sections),1)


if __name__=="__main__":
    unittest.main()

import io
import unittest
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import (NameObject, DictionaryObject, DecodedStreamObject)

from core.review import read_document, ReviewError


def pdf_bytes(pages, password=None):
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        if text:
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
                DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
            stream = DecodedStreamObject()
            stream.set_data(f'BT /F1 12 Tf 72 720 Td ({text}) Tj ET'.encode('ascii'))
            page[NameObject('/Contents')] = writer._add_object(stream)
    if password:
        writer.encrypt(password)
    output = io.BytesIO(); writer.write(output)
    return output.getvalue()


class PDFDocumentTests(unittest.TestCase):
    def test_ordered_text_and_page_markers_are_extracted(self):
        doc = read_document('fictional.pdf', pdf_bytes(['Three interviews.', 'Only these respondents.']))
        self.assertIn('[第1页]\nThree interviews.', doc.text)
        self.assertIn('[第2页]\nOnly these respondents.', doc.text)
        self.assertLess(doc.text.index('Three'), doc.text.index('Only'))
        self.assertIn('未读取图片', doc.notes[0])

    def test_unreadable_pages_are_explicitly_reported(self):
        doc = read_document('mixed.pdf', pdf_bytes(['Fictional record.', None]))
        self.assertIn('第2页没有提取到文字', doc.notes[1])
        self.assertIn('不覆盖这些页', doc.notes[1])

    def test_image_only_or_blank_document_is_not_claimed_as_read(self):
        with self.assertRaisesRegex(ReviewError, '没有可读取的文字'):
            read_document('blank.pdf', pdf_bytes([None]))

    def test_encrypted_pdf_has_a_controlled_error(self):
        with self.assertRaisesRegex(ReviewError, '需要密码'):
            read_document('locked.pdf', pdf_bytes(['Private fictional text.'], 'fictional-password'))

    def test_malformed_pdf_has_a_controlled_error(self):
        with self.assertRaisesRegex(ReviewError, '无法读取'):
            read_document('broken.pdf', b'not a pdf')

    def test_page_limit_is_rejected_without_silent_truncation(self):
        with self.assertRaisesRegex(ReviewError, '80页'):
            read_document('many.pdf', pdf_bytes([None] * 81))

    def test_large_extracted_text_is_not_silently_truncated(self):
        with patch('core.pdf_text.MAX_MATERIAL_CHARS', 20):
            with self.assertRaisesRegex(ReviewError, '不会自动截断'):
                read_document('large.pdf', pdf_bytes(['This fictional report has too much text.']))

    def test_stream_limit_has_a_controlled_error(self):
        with patch('core.pdf_text.MAX_PAGE_STREAM_BYTES', 1):
            with self.assertRaisesRegex(ReviewError, '展开内容过大'):
                read_document('stream.pdf', pdf_bytes(['Fictional text.']))


if __name__ == '__main__':
    unittest.main()

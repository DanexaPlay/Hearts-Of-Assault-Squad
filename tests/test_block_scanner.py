import unittest
from bridge.gem import block_at
from bridge.core import BridgeError

class BlockScannerTests(unittest.TestCase):
    def test_nested_and_escaped_quoted_braces_do_not_end_the_record(self):
        text='prefix {outer {name "brace } and \\" quote"} {numbers 1 2 3}} suffix {next}'
        start=text.index('{')
        self.assertEqual(block_at(text,start),text[start:text.index(' suffix')])
        self.assertEqual(block_at(text,text.index('{next}')),'{next}')

    def test_seeded_nested_records_with_arbitrary_quoted_text(self):
        import random,json
        randomizer=random.Random(51)
        def record(depth):
            text=''.join(randomizer.choice(' abc{}"\\\nЮ123') for _ in range(30))
            children=' '.join(record(depth-1) for _ in range(randomizer.randrange(3))) if depth else ''
            return '{entry '+json.dumps(text,ensure_ascii=False)+' '+children+'}'
        for _ in range(128):
            body=record(4);text='ignored before '+body+' ignored after {other}'
            self.assertEqual(block_at(text,len('ignored before ')),body)

    def test_unterminated_quote_or_nested_record_is_rejected(self):
        for text in ('{outer {nested}', '{name "unfinished }', '{name "trailing\\'):
            with self.assertRaises(BridgeError):block_at(text,0)
        with self.assertRaises(BridgeError):block_at('not a block',0)

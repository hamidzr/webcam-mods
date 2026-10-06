import io
import json
import unittest

from webcam_mods.protocol import (
    MAX_REQUEST_BYTES,
    Request,
    RequestFailure,
    parse_request,
    read_requests,
)


class ProtocolTests(unittest.TestCase):
    def test_oversized_record_drains_then_recovers(self):
        class BoundedStream(io.StringIO):
            def readline(self, size=-1):
                self.assert_bound(size)
                return super().readline(size)

            def assert_bound(self, size):
                if not 0 < size <= MAX_REQUEST_BYTES + 1:
                    raise AssertionError("unbounded read")

        stream = BoundedStream(
            "x" * (MAX_REQUEST_BYTES * 3) + '\n{"id":7,"method":"status"}\n'
        )
        requests = list(read_requests(stream))
        self.assertEqual(len(requests), 2)
        self.assertIsInstance(requests[0], RequestFailure)
        self.assertEqual(requests[1], Request(7, "status", {}))

    def test_eof_without_newline(self):
        self.assertEqual(
            list(read_requests(io.StringIO('{"id":1,"method":"hello"}'))),
            [Request(1, "hello", {})],
        )
        self.assertEqual(
            len(list(read_requests(io.StringIO("x" * (MAX_REQUEST_BYTES + 1))))), 1
        )

    def test_strict_numbers_and_duplicate_members(self):
        for payload in (
            '{"id":1,"method":"start","params":{"fps":NaN}}',
            '{"id":1,"method":"start","params":{"fps":Infinity}}',
            '{"id":1,"method":"start","params":{"fps":1e999}}',
            '{"id":1,"id":2,"method":"status"}',
            '{"id":1,"method":"start","params":{"fps":10,"fps":30}}',
        ):
            with self.subTest(payload=payload):
                self.assertIsInstance(parse_request(payload), RequestFailure)

    def test_ids_and_fields_are_validated(self):
        for identifier in (None, True, [], {}, "", "x" * 129, 2**53, "bad\nidentifier"):
            with self.subTest(identifier=identifier):
                result = parse_request(json.dumps(dict(id=identifier, method="status")))
                self.assertEqual(result.id, None)
                self.assertIsInstance(result, RequestFailure)
        for params in ([], None, "settings"):
            failure = parse_request(
                json.dumps(dict(id=8, method="start", params=params))
            )
            self.assertIsInstance(failure, RequestFailure)
            self.assertEqual(failure.id, 8)
        self.assertEqual(
            parse_request('{"id":"a","method":"status"}'), Request("a", "status", {})
        )

    def test_multibyte_payload_is_bounded_by_bytes(self):
        payload = json.dumps(
            dict(id=1, method="status", params={"text": "\u00e9" * MAX_REQUEST_BYTES}),
            ensure_ascii=False,
        )
        self.assertIsInstance(parse_request(payload), RequestFailure)

    def test_deep_nesting_and_private_payload_are_not_echoed(self):
        line = (
            '{"id":1,"method":"start","params":'
            + "[" * 1500
            + '"private-value"'
            + "]" * 1500
            + "}"
        )
        result = parse_request(line)
        self.assertIsInstance(result, RequestFailure)
        self.assertNotIn("private-value", result.error)

from __future__ import annotations

import unittest
from types import SimpleNamespace

from media_janitor.metadata import metadata_from_tinytag


class MetadataTests(unittest.TestCase):
    def test_maps_common_and_audiobook_specific_fields(self) -> None:
        tag = SimpleNamespace(
            title="Chapter 01",
            album="The Final Empire",
            artist="Brandon Sanderson",
            albumartist="Brandon Sanderson",
            track=1,
            track_total=10,
            disc=1,
            disc_total=2,
            year="2006",
            genre="Audiobook",
            duration=123.5,
            bitrate=64.0,
            samplerate=44100,
            channels=2,
            other={
                "narrator": ["Michael Kramer"],
                "series": ["Mistborn"],
                "series-part": ["1"],
                "ASIN": ["B002V0QCYU"],
                "isbn13": ["9780765311788"],
                "artist": ["Brandon Sanderson"],
            },
        )

        metadata = metadata_from_tinytag(tag)

        self.assertEqual(metadata.album, "The Final Empire")
        self.assertEqual(metadata.artists, ("Brandon Sanderson",))
        self.assertEqual(metadata.album_artists, ("Brandon Sanderson",))
        self.assertEqual(metadata.narrators, ("Michael Kramer",))
        self.assertEqual(metadata.series, "Mistborn")
        self.assertEqual(metadata.series_index, "1")
        self.assertEqual(metadata.asin, "B002V0QCYU")
        self.assertEqual(metadata.isbn, "9780765311788")
        self.assertEqual(metadata.duration_seconds, 123.5)

    def test_missing_optional_attributes_are_safe(self) -> None:
        tag = SimpleNamespace(other={})
        metadata = metadata_from_tinytag(tag)
        self.assertIsNone(metadata.title)
        self.assertEqual(metadata.artists, ())
        self.assertEqual(metadata.other, {})


if __name__ == "__main__":
    unittest.main()

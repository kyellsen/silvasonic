"""BirdNET labels become species rows (ADR-0033)."""

import pytest
from silvasonic.birdnet.species import (
    label_category,
    label_species_id,
    species_row,
    split_label,
)


@pytest.mark.unit
class TestLabelParsing:
    """A BirdNET label is ``<scientific name>_<common name>``."""

    def test_split_label(self) -> None:
        assert split_label("Turdus merula_Eurasian Blackbird") == (
            "Turdus merula",
            "Eurasian Blackbird",
        )

    def test_split_label_without_common_name(self) -> None:
        assert split_label("Noise") == ("Noise", "")

    def test_species_id_is_slug_of_scientific_name(self) -> None:
        assert label_species_id("Turdus merula_Eurasian Blackbird") == "turdus-merula"

    def test_species_id_collapses_non_alphanumerics(self) -> None:
        assert label_species_id("Human vocal_Human vocal") == "human-vocal"
        assert label_species_id("Poecile  (atricapillus)_Chickadee") == "poecile-atricapillus"


@pytest.mark.unit
class TestLabelCategory:
    """A non-species sound class is ``other``; everything else is a bird."""

    def test_bird(self) -> None:
        assert label_category("Turdus merula_Eurasian Blackbird") == "bird"

    def test_identical_halves_are_other(self) -> None:
        assert label_category("Dog_Dog") == "other"
        assert label_category("Engine_Engine") == "other"

    def test_label_without_common_name_is_other(self) -> None:
        assert label_category("Noise") == "other"


@pytest.mark.unit
class TestSpeciesRow:
    """The minimal row inserted the first time a label is detected."""

    def test_bird_row(self) -> None:
        assert species_row("Turdus merula_Eurasian Blackbird") == {
            "id": "turdus-merula",
            "analyzer": "birdnet",
            "label": "Turdus merula_Eurasian Blackbird",
            "scientific_name": "Turdus merula",
            "common_names": {"en": "Eurasian Blackbird"},
            "descriptions": {},
            "category": "bird",
        }

    def test_sound_class_row(self) -> None:
        row = species_row("Dog_Dog")
        assert row["id"] == "dog"
        assert row["category"] == "other"
        assert row["common_names"] == {"en": "Dog"}

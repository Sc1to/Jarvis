"""Believable scene prose for tests: past tense, third person, varied sentences, some dialogue."""

SENTENCES = [
    "Anna crossed the quay as the lamps came on, one after another, like a slow argument being settled.",
    "The fog had thickened.",
    "She did not hurry.",
    "\"You came,\" Jonas said, and he sounded almost disappointed.",
    "A gull screamed somewhere above the warehouses, and then there was nothing but the slap of water against stone and the creak of ropes that had been wet for a hundred years.",
    "\"I had no choice.\"",
    "He turned the ledger over in his hands, thumbing the cloth where the binding had worn through to the board.",
    "Nobody spoke.",
    "Behind them the harbour bell rang twice, a dull flat sound, and a dog began to bark in the lower town.",
    "\"Read it,\" she said. \"Read it aloud, from the beginning, and do not leave anything out.\"",
    "His voice cracked on the first name.",
    "It was hers.",
    "Anna folded her arms, because the alternative was to hit him, and she was a clerk, not a fighter, whatever the town had decided to say about her since the spring.",
    "The lamp over the door guttered.",
    "\"How long have you known?\"",
    "Jonas looked at the water for a while before he answered, and when he did it was in the careful tone of a man laying out coins he could not afford to lose.",
    "Three weeks.",
    "The tide was going out, and the boats shifted in their moorings with a long wooden complaint.",
    "She counted the names on the page, then counted them again, because the first count had come out wrong and the second made it worse.",
    "\"Give it to me.\"",
    "He held on a moment longer than he needed to.",
    "Then he let go, and the weight of it settled into her hands as though it had been waiting for her all along.",
    "Somewhere a shutter banged, and neither of them jumped.",
    "Rain began, thin at first, then steady, ticking on the tarred roofs.",
    "\"Go home, Jonas.\"",
    "He went, but slowly, looking back twice from the end of the quay.",
    "Anna stayed until the lamps were the only warm things left, and the ledger was cold against her ribs.",
    "She thought about the vestry, and the key hidden under the loose flagstone, and the door that had never once been locked.",
    "It would be locked now.",
    "The bell rang again, once, and she began to walk.",
]


def prose(offset: int = 0, sentences: int = 24) -> str:
    """A scene made of `sentences` consecutive sentences from the pool, starting at `offset`, in paragraphs of four."""
    picked = [SENTENCES[(offset + i) % len(SENTENCES)] for i in range(sentences)]
    paragraphs = [" ".join(picked[i: i + 4]) for i in range(0, len(picked), 4)]
    return "\n\n".join(paragraphs)

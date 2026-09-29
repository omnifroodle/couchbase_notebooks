"""Synthetic customer profiles with known answers, for entity resolution.

Every person here is invented. Emails use the ``.example`` top-level domain that
RFC 2606 reserves, and phone numbers the 555-0100 to 555-0199 range set aside
for fiction, so no record can reach a real inbox or phone. Names, cities and
area codes are real, because resolution is hard exactly where real names
collide.

There are two sets, and the question for every record in the second is whether
it belongs to someone in the first:

* **customers** -- the known base, one record per person, as a CRM would hold it.
* **incoming** -- records arriving later from a sign-up form, an order, a support
  ticket or a store till. Each carries the answer in ``truth_customer_id``: the
  known customer it belongs to, or ``None`` for a new person.

Every incoming record is one of these kinds (``truth_kind``):

``returning``
    A known customer again, changed by one to three of :data:`VARIATIONS`.
``relative``
    A new person in a known customer's household (:data:`RELATIONS`): a son
    named after his father, a spouse, a twin. Same surname, often the same
    address and phone. Must *not* be linked.
``namesake``
    A new person with a known customer's exact name and nothing else in common.
``stranger``
    A new person unrelated to anyone.

Some known customers are themselves relatives or namesakes of other known
customers, so a returning record can have a lookalike among its candidates;
``truth_related_to`` on a customer names the other one.

**The rates below are this generator's choices, not facts about the world**, and
they drive any aggregate accuracy measured on it. Report results by kind and by
variation. Which source a record came from also decides which fields it has
(:data:`SOURCES`): a support ticket carries a name and an email, nothing more.

The committed files under ``data/`` are what the notebooks read. They are
regenerated with ``python -m cbnb.profiles``; ``random.Random`` only promises the
same sequence across Python versions for ``random()`` itself, so a regeneration
elsewhere may not reproduce them byte for byte.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

__all__ = [
    "FIELDS",
    "RELATIONS",
    "SOURCES",
    "VARIATIONS",
    "generate",
    "load_profiles",
    "write_profiles",
]

CUSTOMERS_FILE = "profiles_customers.jsonl"
INCOMING_FILE = "profiles_incoming.jsonl"

#: The profile fields, in the order a record is displayed. Everything else on a
#: record is an id, its source, or the answer (``truth_*``), which a matcher must
#: never see.
FIELDS = ["first_name", "last_name", "dob", "email", "phone", "street", "city", "state", "zip"]

#: What a returning customer's new record can differ by.
VARIATIONS = {
    "new_surname": "Surname changed, or double-barrelled, as on marriage.",
    "nickname": "First name replaced by a common nickname (Robert -> Bob).",
    "initial": "First name reduced to an initial (Robert -> R.).",
    "typo": "One slip in the first or last name: a dropped, doubled, swapped or neighbouring key.",
    "moved": "A new street address, often in another city; half the time a new phone too.",
    "new_email": "A different email address.",
    "new_phone": "A different phone number.",
    "dob_swapped": "Day and month of birth transposed (only when both are 12 or under).",
    "swapped": "First and last name entered in each other's fields.",
}

#: How a relative is related to the known customer they resemble, and how often.
#: Same-name parents and children are over-represented on purpose: they are the
#: case where everything but the date of birth can agree.
RELATION_WEIGHTS = {"junior": 0.3, "senior": 0.2, "spouse": 0.3, "twin": 0.2}
RELATIONS = {
    "junior": "Their child, given the same first name. Lives at home (same address) 60% of the time.",
    "senior": "Their parent, whose first name they were given.",
    "spouse": "Their spouse: same surname and address, a different first name.",
    "twin": "Their twin: same surname and date of birth, a different first name.",
}

#: Which fields each source captures. Missing fields are ``None``.
SOURCES = {
    "crm": "The known base: everything, though phone or date of birth is sometimes missing.",
    "signup": "A web sign-up: name and email; phone, date of birth and city when the form asked.",
    "order": "A shipping order: name, full address and phone; usually an email; never a date of birth.",
    "support": "A support ticket: name and email only, sometimes just a first name.",
    "store": "A loyalty card taken at a till: name, phone and zip; sometimes a date of birth.",
}

# --------------------------------------------------------------------------- name data

#: First name -> nicknames. Split by the sex usually given the name only so that
#: a son is named after a father and a spouse gets a plausible name.
MALE = {
    "Robert": ["Bob", "Rob", "Bobby"], "William": ["Bill", "Will", "Billy"],
    "James": ["Jim", "Jimmy", "Jamie"], "John": ["Jack", "Johnny"], "Michael": ["Mike"],
    "Richard": ["Rick", "Rich", "Dick"], "Thomas": ["Tom", "Tommy"], "Charles": ["Charlie", "Chuck"],
    "Joseph": ["Joe", "Joey"], "Christopher": ["Chris"], "Daniel": ["Dan", "Danny"],
    "Matthew": ["Matt"], "Anthony": ["Tony"], "Edward": ["Ed", "Eddie", "Ted"],
    "Andrew": ["Andy", "Drew"], "Joshua": ["Josh"], "Steven": ["Steve"], "Nicholas": ["Nick"],
    "Benjamin": ["Ben"], "Samuel": ["Sam"], "Alexander": ["Alex"], "Jonathan": ["Jon"],
    "Timothy": ["Tim"], "Gregory": ["Greg"], "Patrick": ["Pat"], "Kenneth": ["Ken", "Kenny"],
    "Ronald": ["Ron"], "Donald": ["Don"], "Raymond": ["Ray"], "Lawrence": ["Larry"],
    "Gerald": ["Jerry"], "Francis": ["Frank"], "Peter": ["Pete"], "Frederick": ["Fred"],
    "Henry": ["Hank", "Harry"], "David": ["Dave"], "Jose": ["Pepe"], "Luis": [], "Carlos": [],
    "Mohammed": ["Mo"], "Wei": [], "Hiroshi": [], "Arjun": [], "Dmitri": ["Dima"], "Kwame": [],
    "Mark": [], "Paul": [], "Brian": [], "Kevin": [], "Jason": [],
}
FEMALE = {
    "Elizabeth": ["Liz", "Beth", "Betsy"], "Margaret": ["Maggie", "Peggy", "Meg"],
    "Katherine": ["Kate", "Katie", "Kathy"], "Jennifer": ["Jen", "Jenny"],
    "Patricia": ["Pat", "Patty", "Trish"], "Susan": ["Sue"], "Deborah": ["Deb", "Debbie"],
    "Rebecca": ["Becky", "Becca"], "Victoria": ["Vicky", "Tori"], "Christina": ["Tina", "Chris"],
    "Alexandra": ["Alex", "Sasha"], "Samantha": ["Sam"], "Jessica": ["Jess"], "Abigail": ["Abby"],
    "Barbara": ["Barb"], "Kimberly": ["Kim"], "Melissa": ["Mel", "Missy"], "Amanda": ["Mandy"],
    "Stephanie": ["Steph"], "Nicole": ["Nikki"], "Cynthia": ["Cindy"], "Dorothy": ["Dot"],
    "Theresa": ["Terri", "Tess"], "Josephine": ["Jo", "Josie"], "Madison": ["Maddie"],
    "Olivia": ["Liv"], "Emily": ["Em"], "Sophia": ["Sophie"], "Isabella": ["Bella", "Izzy"],
    "Emma": [], "Maria": [], "Ana": [], "Mei": [], "Yuki": [], "Fatima": [], "Priya": [],
    "Aisha": [], "Olga": [], "Ngozi": [], "Laura": [], "Sarah": [], "Linda": [], "Karen": [],
    "Rachel": [], "Hannah": [],
}
NICKNAMES = {**MALE, **FEMALE}

#: Common US surnames, most common first; sampling favours the front of the list,
#: so some full names recur the way they do in real customer bases.
SURNAMES = """Smith Johnson Williams Brown Jones Garcia Miller Davis Rodriguez Martinez Hernandez
Lopez Gonzalez Wilson Anderson Thomas Taylor Moore Jackson Martin Lee Perez Thompson White Harris
Sanchez Clark Ramirez Lewis Robinson Walker Young Allen King Wright Scott Torres Nguyen Hill Flores
Green Adams Nelson Baker Hall Rivera Campbell Mitchell Carter Roberts Gomez Phillips Evans Turner
Diaz Parker Cruz Edwards Collins Reyes Stewart Morris Morales Murphy Cook Rogers Gutierrez Ortiz
Morgan Cooper Peterson Bailey Reed Kelly Howard Ramos Kim Cox Ward Richardson Watson Brooks Chavez
Wood James Bennett Gray Mendoza Ruiz Hughes Price Alvarez Castillo Sanders Patel Myers Long Ross
Foster Jimenez Chen Wang Singh Kumar Tanaka Sato Okafor Mensah Novak Kowalski Ivanova Schmidt
Fischer Rossi Silva Costa Moreau Dubois Larsen Nilsson""".split()

#: City, state, area codes (several where the city has overlays), first three zip digits.
CITIES = [
    ("Austin", "TX", ["512", "737"], "787"), ("Houston", "TX", ["713", "281", "832"], "770"),
    ("Dallas", "TX", ["214", "469", "972"], "752"), ("Denver", "CO", ["303", "720"], "802"),
    ("Portland", "OR", ["503", "971"], "972"), ("Portland", "ME", ["207"], "041"),
    ("Seattle", "WA", ["206"], "981"), ("Chicago", "IL", ["312", "773", "872"], "606"),
    ("Columbus", "OH", ["614", "380"], "432"), ("Atlanta", "GA", ["404", "678", "470"], "303"),
    ("Miami", "FL", ["305", "786"], "331"), ("Boston", "MA", ["617", "857"], "021"),
    ("Philadelphia", "PA", ["215", "267"], "191"), ("Phoenix", "AZ", ["602", "480"], "850"),
    ("San Diego", "CA", ["619", "858"], "921"), ("Sacramento", "CA", ["916"], "958"),
    ("Minneapolis", "MN", ["612"], "554"), ("Nashville", "TN", ["615", "629"], "372"),
    ("Raleigh", "NC", ["919", "984"], "276"), ("Kansas City", "MO", ["816"], "641"),
    ("Pittsburgh", "PA", ["412"], "152"), ("Salt Lake City", "UT", ["801", "385"], "841"),
    ("Albuquerque", "NM", ["505"], "871"), ("Omaha", "NE", ["402"], "681"),
    ("Springfield", "IL", ["217"], "627"), ("Springfield", "MO", ["417"], "658"),
    ("Springfield", "MA", ["413"], "011"), ("Richmond", "VA", ["804"], "232"),
    ("Tucson", "AZ", ["520"], "857"), ("Boise", "ID", ["208"], "837"),
]

STREETS = """Oak Maple Cedar Pine Elm Walnut Willow Birch Hickory Chestnut Park Lake Hill River
Spring Meadow Forest Ridge Valley Sunset Highland Washington Lincoln Jefferson Madison Franklin
Jackson Church Mill Main Center Union Market Garden Orchard Prospect Railroad Bridge""".split()
STREET_TYPES = ["St", "Ave", "Rd", "Dr", "Ln", "Ct", "Blvd", "Way", "Pl"]
EMAIL_DOMAINS = ["inbox.example", "mail.example", "post.example", "webmail.example", "letters.example"]

KEYBOARD = {
    "a": "qwsz", "b": "vghn", "c": "xdfv", "d": "serfcx", "e": "wsdr", "f": "drtgvc", "g": "ftyhbv",
    "h": "gyujnb", "i": "ujko", "j": "huikmn", "k": "jiolm", "l": "kop", "m": "njk", "n": "bhjm",
    "o": "iklp", "p": "ol", "q": "wa", "r": "edft", "s": "awedxz", "t": "rfgy", "u": "yhji",
    "v": "cfgb", "w": "qase", "x": "zsdc", "y": "tghu", "z": "asx",
}

# --------------------------------------------------------------------------- people


@dataclass
class Person:
    """One real-world individual. Records are views of a person, possibly changed."""

    pid: int
    sex: str
    first_name: str
    last_name: str
    dob: date
    email: str
    phone: str
    street: str
    city: str
    state: str
    zip: str
    related_to: int | None = None
    relation: str | None = None
    extra: dict = field(default_factory=dict)


class _Generator:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.people: list[Person] = []
        self.used_phones: set[str] = set()
        self.used_emails: set[str] = set()

    # ---- primitives

    def surname(self) -> str:
        # Weighted towards the front of the list: rank r has weight 1 / (r + 8).
        weights = [1 / (rank + 8) for rank in range(len(SURNAMES))]
        return self.rng.choices(SURNAMES, weights)[0]

    def first_name(self, sex: str) -> str:
        names = list(MALE if sex == "m" else FEMALE)
        weights = [1 / (rank + 6) for rank in range(len(names))]
        return self.rng.choices(names, weights)[0]

    def dob(self, low: int = 1945, high: int = 2005) -> date:
        start, end = date(low, 1, 1), date(high, 12, 31)
        return start + timedelta(days=self.rng.randrange((end - start).days))

    def place(self) -> tuple[str, str, list[str], str]:
        return self.rng.choice(CITIES)

    def address(self, city=None) -> tuple[str, str, str, str]:
        name, state, _, zip3 = city or self.place()
        street = f"{self.rng.randrange(10, 9990)} {self.rng.choice(STREETS)} {self.rng.choice(STREET_TYPES)}"
        if self.rng.random() < 0.15:
            street += f" Apt {self.rng.randrange(1, 40)}{self.rng.choice('ABCD')}"
        return street, name, state, f"{zip3}{self.rng.randrange(0, 100):02d}"

    def phone(self, city=None) -> str:
        area_codes = (city or self.place())[2]
        for _ in range(500):
            area = self.rng.choice(area_codes)
            number = f"({area}) 555-01{self.rng.randrange(100):02d}"
            if number not in self.used_phones:
                self.used_phones.add(number)
                return number
        # The city's fictional numbers are used up; borrow another city's area code.
        return self.phone(self.rng.choice(CITIES))

    def email(self, first: str, last: str, dob: date) -> str:
        f, s = first.lower(), last.lower().replace(" ", "").replace("-", "")
        for _ in range(50):
            handle = self.rng.choice([
                f"{f}.{s}", f"{f}{s}", f"{f[0]}{s}", f"{f}.{s[0]}", f"{f}_{s}", f"{s}.{f}",
                f"{f}{self.rng.randrange(1, 99)}",
            ])
            if self.rng.random() < 0.5:
                handle += self.rng.choice([str(dob.year % 100).zfill(2), str(self.rng.randrange(1, 999))])
            address = f"{handle}@{self.rng.choice(EMAIL_DOMAINS)}"
            if address not in self.used_emails:
                self.used_emails.add(address)
                return address
        raise RuntimeError("could not find an unused email")

    def city_of(self, person: Person):
        return next(c for c in CITIES if c[0] == person.city and c[1] == person.state)

    # ---- people

    def new_person(self, sex=None, first=None, last=None, dob=None, home: Person | None = None,
                   related_to=None, relation=None, same_phone=False) -> Person:
        sex = sex or self.rng.choice("mf")
        first = first or self.first_name(sex)
        last = last or self.surname()
        dob = dob or self.dob()
        if home is not None:
            street, city, state, zip_ = home.street, home.city, home.state, home.zip
            place = self.city_of(home)
        else:
            place = self.place()
            street, city, state, zip_ = self.address(place)
        phone = home.phone if (home is not None and same_phone) else self.phone(place)
        person = Person(len(self.people), sex, first, last, dob, self.email(first, last, dob), phone,
                        street, city, state, zip_, related_to, relation)
        self.people.append(person)
        return person

    def relative(self, of: Person, relation: str) -> Person | None:
        """A new person related to ``of``, or None if the relation does not fit them."""
        rng = self.rng
        at_home = rng.random() < 0.6
        if relation == "junior":
            if of.sex != "m" or of.dob.year > 1982:
                return None
            dob = self.dob(of.dob.year + 22, min(of.dob.year + 38, 2006))
            return self.new_person("m", of.first_name, of.last_name, dob, of if at_home else None,
                                   of.pid, relation, same_phone=at_home and rng.random() < 0.5)
        if relation == "senior":
            if of.sex != "m" or of.dob.year < 1970:
                return None
            dob = self.dob(of.dob.year - 38, of.dob.year - 22)
            return self.new_person("m", of.first_name, of.last_name, dob, of if at_home else None,
                                   of.pid, relation, same_phone=at_home and rng.random() < 0.5)
        if relation == "spouse":
            sex = "f" if of.sex == "m" else "m"
            first = self.first_name(sex)
            year = max(1945, min(2005, of.dob.year + rng.randrange(-6, 7)))
            return self.new_person(sex, first, of.last_name, self.dob(year, year), of, of.pid,
                                   relation, same_phone=rng.random() < 0.5)
        if relation == "twin":
            sex = rng.choice("mf")
            first = self.first_name(sex)
            while first == of.first_name:
                first = self.first_name(sex)
            return self.new_person(sex, first, of.last_name, of.dob, of if at_home else None,
                                   of.pid, relation, same_phone=at_home and rng.random() < 0.5)
        raise ValueError(relation)

    def namesake(self, of: Person) -> Person:
        return self.new_person(of.sex, of.first_name, of.last_name, related_to=of.pid,
                               relation="namesake")

    # ---- records

    def record(self, person: Person, source: str) -> dict:
        """A record of ``person`` as ``source`` would capture it."""
        rng = self.rng
        rec = {k: getattr(person, k) for k in FIELDS}
        rec["dob"] = person.dob.isoformat()
        keep = {
            "crm": lambda k: not (k == "phone" and rng.random() < 0.1)
            and not (k == "dob" and rng.random() < 0.15),
            "signup": lambda k: k in {"first_name", "last_name", "email"}
            or (k == "phone" and rng.random() < 0.5) or (k == "dob" and rng.random() < 0.6)
            or (k in {"city", "state"} and rng.random() < 0.7),
            "order": lambda k: k not in {"dob"} and not (k == "email" and rng.random() < 0.2),
            "support": lambda k: k in {"first_name", "email"}
            or (k == "last_name" and rng.random() < 0.7),
            "store": lambda k: k in {"first_name", "last_name", "phone", "zip"}
            or (k == "dob" and rng.random() < 0.5),
        }[source]
        # Decide every field first, so the random draws do not depend on field order.
        decisions = {k: keep(k) for k in FIELDS}
        if source == "signup":
            decisions["state"] = decisions["city"]
        return {k: (v if decisions[k] else None) for k, v in rec.items()}

    def vary(self, rec: dict, person: Person, kinds: list[str]) -> dict:
        """Apply the named :data:`VARIATIONS` to a record, in order."""
        rng = self.rng
        rec = dict(rec)
        # Name changes before the typo that might land in them, and the swap last,
        # so a nickname is not written into a field the swap has already moved.
        for kind in sorted(kinds, key=list(VARIATIONS).index):
            if kind == "nickname":
                rec["first_name"] = rng.choice(NICKNAMES[person.first_name])
            elif kind == "typo":
                key = rng.choice([k for k in ("first_name", "last_name") if rec[k]])
                rec[key] = _typo(rec[key], rng)
            elif kind == "initial":
                rec["first_name"] = f"{person.first_name[0]}."
            elif kind == "swapped":
                rec["first_name"], rec["last_name"] = rec["last_name"], rec["first_name"]
            elif kind == "new_surname":
                other = self.surname()
                new = rng.choice([other, f"{person.last_name}-{other}"])
                if rec["last_name"]:
                    rec["last_name"] = new
                if rec["email"]:
                    rec["email"] = self.email(rec["first_name"] or person.first_name, other, person.dob)
            elif kind == "moved":
                place = rng.choice(CITIES) if rng.random() < 0.6 else self.city_of(person)
                street, city, state, zip_ = self.address(place)
                for k, v in {"street": street, "city": city, "state": state, "zip": zip_}.items():
                    if rec[k]:
                        rec[k] = v
                if rec["phone"] and rng.random() < 0.5:
                    rec["phone"] = self.phone(place)
            elif kind == "new_email":
                rec["email"] = self.email(person.first_name, person.last_name, person.dob)
            elif kind == "new_phone":
                rec["phone"] = self.phone(self.city_of(person))
            elif kind == "dob_swapped":
                d = person.dob
                rec["dob"] = date(d.year, d.day, d.month).isoformat()
            else:
                raise ValueError(kind)
        return rec

    def applicable(self, rec: dict, person: Person) -> list[str]:
        """Variations that would visibly change this record."""
        out = ["typo", "swapped"] if rec["first_name"] and rec["last_name"] else ["typo"]
        if rec["first_name"] and NICKNAMES[person.first_name]:
            out.append("nickname")
        if rec["first_name"]:
            out.append("initial")
        if rec["last_name"] or rec["email"]:
            out.append("new_surname")
        if rec["street"] or rec["city"] or rec["zip"]:
            out.append("moved")
        if rec["email"]:
            out.append("new_email")
        if rec["phone"]:
            out.append("new_phone")
        if rec["dob"] and person.dob.day <= 12 and person.dob.day != person.dob.month:
            out.append("dob_swapped")
        return out


def _typo(word: str, rng: random.Random) -> str:
    if len(word) < 3:
        return word + word[-1]
    i = rng.randrange(1, len(word) - 1)
    kind = rng.choice(["drop", "double", "swap", "neighbour"])
    if kind == "drop":
        return word[:i] + word[i + 1:]
    if kind == "double":
        return word[:i] + word[i] + word[i:]
    if kind == "swap" and word[i] != word[i + 1]:
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    near = KEYBOARD.get(word[i].lower())
    return word[:i] + rng.choice(near) + word[i + 1:] if near else word[:i] + word[i + 1:]


def generate(
    seed: int = 20260929,
    customers: int = 1000,
    returning: int = 220,
    relatives: int = 80,
    namesakes: int = 40,
    strangers: int = 60,
    lookalike_share: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the known base and the incoming records. See the module docstring.

    ``lookalike_share`` of the known customers are created as relatives or
    namesakes of other known customers, so a returning record's candidates can
    include a lookalike.
    """
    g = _Generator(seed)
    rng = g.rng

    # The known base: mostly unrelated people, some households and shared names.
    known: list[Person] = []
    while len(known) < customers:
        if known and rng.random() < lookalike_share:
            relation = rng.choices([*RELATION_WEIGHTS, "namesake"],
                                   [*RELATION_WEIGHTS.values(), 0.25])[0]
            person = None
            while person is None:
                base = rng.choice(known)
                person = g.namesake(base) if relation == "namesake" else g.relative(base, relation)
        else:
            person = g.new_person()
        known.append(person)
    known_ids = {p.pid: f"C{i + 1:04d}" for i, p in enumerate(known)}

    customer_rows = []
    for p in known:
        rec = g.record(p, "crm")
        customer_rows.append({
            "customer_id": known_ids[p.pid], "source": "crm", **rec,
            "truth_related_to": known_ids.get(p.related_to), "truth_relation": p.relation,
        })

    # Incoming records.
    incoming_rows = []

    def add(rec: dict, source: str, kind: str, customer_id, variations=(), relation=None, of=None):
        incoming_rows.append({
            "record_id": "", "source": source, **rec, "truth_customer_id": customer_id,
            "truth_kind": kind, "truth_variations": list(variations), "truth_relation": relation,
            "truth_related_to": of,
        })

    incoming_sources = ["signup", "order", "support", "store"]
    for p in rng.sample(known, returning):
        source = rng.choice(incoming_sources)
        rec = g.record(p, source)
        options = g.applicable(rec, p)
        # Most returning records change one thing; a few change up to three.
        n = min(len(options), rng.choices([1, 2, 3], [0.55, 0.3, 0.15])[0])
        kinds = rng.sample(options, n)
        # A nickname and an initial both replace the first name; keep one of them.
        if "nickname" in kinds and "initial" in kinds:
            kinds.remove("initial")
        add(g.vary(rec, p, kinds), source, "returning", known_ids[p.pid], kinds)

    for _ in range(relatives):
        relation = rng.choices(list(RELATION_WEIGHTS), list(RELATION_WEIGHTS.values()))[0]
        person = None
        while person is None:
            base = rng.choice(known)
            person = g.relative(base, relation)
        source = rng.choice(incoming_sources)
        add(g.record(person, source), source, "relative", None,
            relation=relation, of=known_ids[base.pid])
    for base in rng.sample(known, namesakes):
        person = g.namesake(base)
        source = rng.choice(incoming_sources)
        add(g.record(person, source), source, "namesake", None,
            relation="namesake", of=known_ids[base.pid])
    for _ in range(strangers):
        source = rng.choice(incoming_sources)
        add(g.record(g.new_person(), source), source, "stranger", None)

    rng.shuffle(incoming_rows)
    for i, row in enumerate(incoming_rows):
        row["record_id"] = f"N{i + 1:04d}"
    return pd.DataFrame(customer_rows), pd.DataFrame(incoming_rows)


def write_profiles(directory: str | Path, **kwargs) -> tuple[Path, Path]:
    """Generate and write both files as JSON lines. ``kwargs`` go to :func:`generate`."""
    directory = Path(directory)
    customers, incoming = generate(**kwargs)
    paths = directory / CUSTOMERS_FILE, directory / INCOMING_FILE
    for frame, path in zip((customers, incoming), paths, strict=True):
        frame = frame.astype(object).where(frame.notna(), None)  # null in JSON, not NaN
        with open(path, "w") as handle:
            for row in frame.to_dict(orient="records"):
                handle.write(json.dumps(row) + "\n")
    return paths


def load_profiles() -> tuple[pd.DataFrame, pd.DataFrame]:
    """The committed known customers and incoming records, as two frames.

    Outside a checkout (``cbnb`` installed on its own) there is no ``data/``
    directory, so the sets are generated afresh, which may differ slightly from
    the committed ones on another Python version.
    """
    from cbnb.datasets import data_dir

    directory = data_dir()
    if directory is None or not (directory / CUSTOMERS_FILE).exists():
        return generate()
    frames = []
    for name in (CUSTOMERS_FILE, INCOMING_FILE):
        rows = [json.loads(line) for line in (directory / name).read_text().splitlines() if line]
        frames.append(pd.DataFrame(rows).astype(object).where(lambda f: f.notna(), None))
    return frames[0], frames[1]


if __name__ == "__main__":
    from cbnb.bootstrap import repo_root

    root = repo_root()
    if root is None:
        raise SystemExit("Run from a checkout: the files are written to its data/ directory.")
    for path in write_profiles(root / "data"):
        print(f"wrote {path.relative_to(root)}")

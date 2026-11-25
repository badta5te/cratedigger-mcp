# runout-mcp

A personal assistant layer over one owner's Discogs world: the catalog, the owner's Collection and Wantlist, and the marketplace.

## Language

### Catalog

**Master**:
A musical work as a whole (an album or single), independent of any particular edition. Groups all of its Releases.
_Avoid_: album (when the edition matters), title

**Release**:
One specific edition of a Master: a concrete label, catalog number, country, year and format. The canonical unit everything else refers to.
_Avoid_: pressing, edition, version, record (when an edition is meant)

**Format**:
The physical medium of a Release: Vinyl, CD, Cassette and so on, with details such as LP, 7", 180g.
_Avoid_: type, media, release type

### Owner

**Owner**:
The single person whose Discogs account, Collection, Wantlist and Record notes the system serves. There are no other users.
_Avoid_: user, account, customer

**Collection**:
The set of Copies the Owner has.

**Copy**:
One physical item of a Release in the Owner's Collection. The Owner can have several Copies of the same Release, each with its own condition.
_Avoid_: item, instance, "my record"

**Wantlist**:
The Releases the Owner wants to acquire.

**Want**:
One Release on the Wantlist.
_Avoid_: wish, wantlist item

### Marketplace

**Lowest price**:
The cheapest current Marketplace listing of a Release, in any condition, excluding shipping. The only price signal available.
_Avoid_: price (unqualified), market price, median price

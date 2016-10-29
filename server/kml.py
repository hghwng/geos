"""
This module is for generating Google Earth KML files
for displaying tiled web maps as overlay.

This module comes with three major classes:
    * KMLMaster:
        Create a kml that contains network links to
        multiple KMLMapRoots (-> overview over available maps)
    * KMLMapRoot:
        Root document of a Map. Can be used standalone to display
        one specific map.
    * KMLRegion:
        A region containing multiple tiles and four network links to the
        next zoom level.

The number of tiles per KML Region can be specified with the `log_tiles_per_row`
parameter. The number of tiles per region impacts the number of http requests. Many
tiles per region will reduce the amount of KML documents requested and therefore
reduce server load.

Understanding the `log_tiles_per_row` is likely to require some explanation:
    A KML region consists of
        * always four network links to the next zoom level
        * ground overlays (the actual tile images)

    The following constraints apply
        * A KML region is always a square (nrow = ncol)
        * the number of ground overlays per row is always a power of two.

    `log_tile_per_row` is the log2(tiles per row per region).

        Example: `log_tiles_per_row = 0` -> 2**0 = 1 tile per row -> 1 tile per region
            Network Links           Ground Overlay
                 --- ---               -------
                | 1 | 2 |             |       |
                 --- ---              |   1   |
                | 3 | 4 |             |       |
                 --- ---               -------

        Example: `log_tiles_per_row = 1` -> 2**1 = 2 tilese per row -> four tiles per region
            Network Links           Ground Overlays
                 --- ---               -------
                | 1 | 2 |             | 1 | 2 |
                 --- ---               --- ---
                | 3 | 4 |             | 3 | 4 |
                 --- ---               -------
"""


from pykml.factory import KML_ElementMaker as KML
from geometry import *
from lxml import etree

DEFAULT_MAX_LOD_PIXELS = -1
DEFAULT_MIN_LOD_PIXELS = 128


def kml_element_name(grid_coords, elem_id="KML"):
    """Create a unique element name for KML"""
    return "_".join(str(x) for x in [elem_id, grid_coords.zoom, grid_coords.x, grid_coords.y])


def kml_lat_lon_box(geo_bb):
    """
    Create the north/south/east/west tags
    for a <LatLonBox> or <LatLonAltBox> Bounding Box

    Args:
        geo_bb: GeographicBB
    """
    return (
        KML.north(geo_bb.max.lat),
        KML.south(geo_bb.min.lat),
        KML.east(geo_bb.max.lon),
        KML.west(geo_bb.min.lon)
    )


def kml_lod(min_lod_pixels=DEFAULT_MIN_LOD_PIXELS, max_lod_pixels=DEFAULT_MAX_LOD_PIXELS):
    """
    Create the KML LevelOfDetail (LOD) Tag.

    In a Region, the <minLodPixels> and <maxLodPixels> elements allow you to specify
    an area of the screen (in square pixels). When your data is projected onto the screen,
    it must occupy an area of the screen that is greater than <minLodPixels> and less
    than <maxLodPixels> in order to be visible. Once the projected size of the Region goes
    outside of these limits, it is no longer visible, and the Region becomes inactive.
    (from https://developers.google.com/kml/documentation/kml_21tutorial)

    Args:
        min_lod_pixels (int):
        max_lod_pixels (int):
    """
    return KML.Lod(
        KML.minLodPixels(min_lod_pixels),
        KML.maxLodPixels(max_lod_pixels))


def kml_region(region_coords, min_lod_pixels=DEFAULT_MIN_LOD_PIXELS,
               max_lod_pixels=DEFAULT_MAX_LOD_PIXELS):
    """Create the KML <Region> tag with the appropriate geographic coordinates"""
    bbox = region_coords.geographic_bounds()
    return KML.Region(
        kml_lod(min_lod_pixels=min_lod_pixels, max_lod_pixels=max_lod_pixels),
        KML.LatLonAltBox(
            *kml_lat_lon_box(bbox)
        )
    )


def kml_network_link(href, name=None, region_coords=None, visible=True):
    """
    Create the KML <NetworkLink> Tag for a
    certain Region in the RegionGrid.

    Args:
        region_coords (RegionCoordinate):
        href (str): the href attribute of the NetworkLink
        name (str): KML <name>
        visible (bool): If true the network link will appear as 'visible'
            (i.e. checked) in Google Earth.

    Returns:
        KMLElement:

    """
    nl = KML.NetworkLink()
    if name is None and region_coords is not None:
        name = kml_element_name(region_coords, "NL")
    if name is not None:
        nl.append(KML.name(name))
    if region_coords is not None:
        min_lod_pixels = DEFAULT_MIN_LOD_PIXELS * (2 ** region_coords.log_tiles_per_row)
        nl.append(kml_region(region_coords, min_lod_pixels=min_lod_pixels))
    if not visible:
        nl.append(KML.visibility(0))

    nl.append(KML.Link(
        KML.href(href), KML.viewRefreshMode("onRegion")))

    return nl


def kml_ground_overlay(tile_coords, tile_url):
    """
    Create a KML <GroundOverlay> for a certain TileCoordinate.

    Args:
        tile_coords (TileCoordinate): TileCoordinate
        tile_url (str): web-url to the actual tile image.

    Returns:
        KMLElement:

    """
    return KML.GroundOverlay(
        KML.name(kml_element_name(tile_coords, "GO")),
        KML.drawOrder(tile_coords.zoom),
        KML.Icon(
            KML.href(tile_url)
        ),
        KML.LatLonBox(
            *kml_lat_lon_box(tile_coords.geographic_bounds())
        ),
    )


class URLFormatter:
    """Responsible for generating absolute URLs to
    KML Map files"""

    def __init__(self, server_name, url_scheme="http"):
        self.server_name = server_name
        self.url_scheme = url_scheme

    def get_abs_url(self, rel_url):
        """Create an absolute url with respect to SERVER_NAME"""
        rel_url = rel_url.lstrip("/")
        return "{}://{}/{}".format(self.url_scheme, self.server_name, rel_url)

    def get_map_root_url(self, mapsource):
        return self.get_abs_url("/maps/{}.kml".format(mapsource.id))

    def get_map_url(self, mapsource, grid_coords):
        return self.get_abs_url(
                "/maps/{}/{}/{}/{}.kml".format(mapsource.id, grid_coords.zoom,
                                               grid_coords.x, grid_coords.y))


class KMLMap:
    MIME_TYPE = "application/vnd.google-earth.kml+xml"

    def __init__(self, url_formatter):
        """
        Args:
            url_formatter (URLFormatter): URLFormatter object
        """
        self.url_formatter = url_formatter
        self.kml_doc = KML.Document()
        self.kml_root = KML.kml(self.kml_doc)

    def add_elem(self, kml_elem):
        """Add an element to the KMLDocument"""
        self.kml_doc.append(kml_elem)

    def add_elems(self, kml_elems):
        """
        Add elements from an iterator.

        Args:
            kml_elems (iterable of KMLElements): any iterator containing KML elements.
                Can also be a KMLMap instance
        """
        for kml_elem in kml_elems:
            self.add_elem(kml_elem)

    def get_kml(self):
        """Return the KML Document as formatted kml/xml"""
        return etree.tostring(self.kml_root, pretty_print=True, xml_declaration=True)

    def __iter__(self):
        yield from self.kml_doc.iterchildren()


class KMLMaster(KMLMap):
    """Create a KML Master document that
    contains NetworkLinks to all Maps
    in the mapsource directory"""

    def __init__(self, url_formatter, mapsources):
        super().__init__(url_formatter)
        for map_s in mapsources:
            self.add_elem(
                kml_network_link(self.url_formatter.get_map_root_url(map_s),
                                 name=map_s.name, visible=False)
            )


class KMLMapRoot(KMLMap):
    """Create root Document for an
    individual Map. Can be used as standalone KML
    to display that map only"""

    def __init__(self, url_formatter, mapsource, log_tiles_per_row):
        super().__init__(url_formatter)
        self.mapsource = mapsource

        assert(log_tiles_per_row in range(0, 5))
        self.log_tiles_per_row = log_tiles_per_row

        # on zoom level 0, one cannot have more than one tile per region.
        zoom = max(mapsource.min_zoom, log_tiles_per_row)

        n_tiles = 2 ** zoom
        tile_per_row = 2 ** self.log_tiles_per_row
        n_regions = n_tiles//tile_per_row
        assert n_tiles % tile_per_row == 0
        self.add_elem(KML.name("{} root".format(mapsource.name)))
        for x, y in griditer(0, 0, n_regions):
            self.add_elems(KMLRegion(self.url_formatter, self.mapsource,
                                     self.log_tiles_per_row, zoom, x, y))


class KMLRegion(KMLMap):
    """Create a KML that displays the actual tiles
    as GroundOverlay and contains NetworkLinks
    to the next LevelOfDetail.
    """

    def __init__(self, url_formatter, mapsource, log_tiles_per_row, zoom, x, y):
        super().__init__(url_formatter)
        self.mapsource = mapsource
        rc = RegionCoordinate(zoom, x, y, log_tiles_per_row)

        self.add_elem(KML.name(kml_element_name(rc, "DOC")))

        for tc in rc.get_tiles():
            self.add_ground_overlay(tc)
        if zoom < mapsource.max_zoom:
            for rc_child in rc.zoom_in():
                self.add_network_link(rc_child)

    def add_ground_overlay(self, tile_coords):
        tile_url = self.mapsource.get_tile_url(tile_coords.zoom, tile_coords.x, tile_coords.y)
        self.add_elem(kml_ground_overlay(tile_coords, tile_url))

    def add_network_link(self, region_coords):
        href = self.url_formatter.get_map_url(self.mapsource, region_coords)
        self.add_elem(kml_network_link(href, region_coords=region_coords))

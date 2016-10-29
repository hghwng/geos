"""geometry.py:
Conversions between WGS84, Cartesian, Mercator and TMS coordinates and bounding boxes,
useful for converting geographic view ports as generated by Google Earth to TMS bounding boxes
"""

import math
import itertools
from abc import ABCMeta, abstractmethod

__author__ = "Martin Loetzsch, Gregor Sturm"
__licence__ = "Apache 2.0"

_earthradius = 6378137.0

_tilesize = _initial_resolution = _originshift = None
_originshift_180 = _180_originshift = None

_pi_2 = math.pi / 2.0
_pi_180 = math.pi / 180.0
_pi_360 = math.pi / 360.0
_180_pi = 180.0 / math.pi


def init_geometry(tilesize=256.0):
    global _tilesize, _initialresolution, _originshift
    global _originshift_180, _180_originshift
    _tilesize = tilesize
    _initialresolution = 2 * math.pi * 6378137 / _tilesize
    _originshift = 2 * math.pi * 6378137 / 2.0
    _originshift_180 = _originshift / 180.0
    _180_originshift = 180.0 / _originshift


init_geometry()


def griditer(x, y, ncol, nrow=None, step=1):
    """
    Iterate through a grid of tiles.

    Args:
        x (int): x start-coordinate
        y (int): y start-coordinate
        ncol (int): number of tile columns
        nrow (int): number of tile rows. If not specified, this
            defaults to ncol, s.t. a quadratic region is
            generated
        step (int): clear. Analogous to range().

    Yields:
        Tuple: all tuples (x, y) in the region delimited by
            (x, y), (x + ncol, y + ncol).

    """
    if nrow is None:
        nrow = ncol
    yield from itertools.product(range(x, x + ncol, step),
                                 range(y, y + nrow, step))


class GeographicCoordinate:
    """
    Represents a WGS84 Datum
    x: longitude in degrees
    y: latitude in degrees
    height: height in meters above the surface of the earth spheroid
    """

    def __init__(self, lon=None, lat=None, height=0.0):
        self.lon = lon
        self.lat = lat
        self.height = height

    def to_cartesian(self):
        r = (_earthradius + self.height)
        cosx = math.cos(_pi_180 * self.lon)
        cosy = math.cos(_pi_180 * self.lat)
        sinx = math.sin(_pi_180 * self.lon)
        siny = math.sin(_pi_180 * self.lat)
        return CartesianCoordinate(r * cosy * cosx, r * cosy * sinx, r * siny)

    def to_mercator(self):
        return MercatorCoordinate(
            self.lon * _originshift_180,
            math.log(math.tan((90 + self.lat) * _pi_360)) / _pi_180 * _originshift_180)

    def __str__(self):
        return "<lon: " + str(self.lon) + ", lat: " + str(self.lat) + ", height: " \
               + str(self.height) + ">"


class GeographicBB:
    """ A bounding box defined by two geographic coordinates """

    def __init__(self, min_lon=None, min_lat=None, max_lon=None, max_lat=None):
        self.min = GeographicCoordinate(min_lon, min_lat)
        self.max = GeographicCoordinate(max_lon, max_lat)

    def intersection(self, other):
        intersects = self.min.lon <= other.max.lon and self.max.lon >= other.min.lon and \
                     self.min.lat <= other.max.lat and self.max.lat >= other.min.lat
        if intersects:
            return GeographicBB(max(self.min.lon, other.min.lon),
                                max(self.min.lat, other.min.lat),
                                min(self.max.lon, other.max.lon),
                                min(self.max.lat, other.max.lat))
        elif self.max.lon > 180.0:
            return GeographicBB(-180, self.min.lat,
                                self.max.lon - 360.0, self.max.lat).intersection(other)

    def center(self):
        return GeographicCoordinate(self.min.lon + (self.max.lon - self.min.lon) / 2,
                                    self.min.lat + (self.max.lat - self.min.lat) / 2)

    def to_mercator(self):
        return MercatorBB(self.min.to_mercator(), self.max.to_mercator())

    def __str__(self):
        return "<geographic min: " + str(self.min) + ", max: " + str(self.max) + ">"


class CartesianCoordinate:
    """ Represents a coordinate in a geocentric Cartesian coordinate system """

    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

    def __sub__(self, other):
        return CartesianCoordinate(self.x - other.x, self.y - other.y, self.z - other.z)

    def length(self):
        return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)

    def __str__(self):
        return "<x: " + str(self.x) + ", y: " + str(self.y) + ", z: " + str(self.z) + ">"


class MercatorCoordinate:
    """ Represents a coordinate in Spherical Mercator EPSG:900913 """

    def __init__(self, x=None, y=None):
        self.x = x
        self.y = y

    def to_tile(self, zoom):
        res = _initialresolution / (2 ** zoom)

        def transform(x):
            return int(math.ceil(((x + _originshift) / res) / _tilesize) - 1)

        return TileCoordinate(zoom, transform(self.x),
                              (2 ** zoom - 1) - transform(self.y))

    def to_geographic(self):
        return GeographicCoordinate(
            None if self.x is None else self.x * _180_originshift,
            None if self.y is None
            else (2 * math.atan(math.exp(self.y * _180_originshift * _pi_180)) - _pi_2) \
                 * _180_pi)

    def __str__(self):
        return "<x: " + str(self.x) + ", y: " + str(self.y) + ">"


class MercatorBB:
    """ A bounding box defined by two mercator coordinates """

    def __init__(self, _min=MercatorCoordinate, _max=MercatorCoordinate):
        self.min = _min
        self.max = _max

    def to_tile(self, zoom):
        """ Converts EPSG:900913 to tile coordinates in given zoom level """
        p1 = self.min.to_tile(zoom)
        p2 = self.max.to_tile(zoom)
        return GridBB(zoom, p1.x, p2.y, p2.x, p1.y)

    def __str__(self):
        return "<mercator min: " + str(self.min) + ", max: " + str(self.max) + ">"


class GridCoordinate(metaclass=ABCMeta):
    """
    a simple representation of a position in a multi-zoom-level grid.
    """

    def __init__(self, zoom, x, y):
        self.zoom = zoom
        self.x = x
        self.y = y

    @abstractmethod
    def zoom_in(self):
        """
        Yields:
            GridCoordinate: the four tiles of the next zoom level
        """
        return

    def encode_quad_tree(self):
        quad_key = ""
        tx = self.x
        ty = self.y
        for i in range(self.zoom, 0, -1):
            digit = 0
            mask = 1 << (i - 1)
            if (tx & mask) != 0:
                digit += 1
            if (ty & mask) != 0:
                digit += 2
            quad_key += str(digit)
        return quad_key

    def __str__(self):
        return "<zoom: " + str(self.zoom) + ", x: " + str(self.x) + ", y: " + str(self.y) + ">"


class TileCoordinate(GridCoordinate):
    """ Represents a coordinate in a worldwide tile grid. """

    def to_mercator(self):
        res = _initialresolution / (2 ** self.zoom)
        return MercatorCoordinate(
            None if self.x is None else self.x * _tilesize * res - _originshift,
            None if self.y is None else (2 ** self.zoom - self.y) * _tilesize * res - _originshift)

    def to_geographic(self):
        return self.to_mercator().to_geographic()

    def geographic_bounds(self):
        p1 = self.to_geographic()
        p2 = TileCoordinate(self.zoom, self.x + 1, self.y + 1).to_geographic()
        return GeographicBB(p1.lon, p2.lat, p2.lon, p1.lat)

    def zoom_in(self):
        for x, y in griditer(self.x * 2, self.y * 2, ncol=2):
            yield TileCoordinate(self.zoom + 1, x, y)


class RegionCoordinate(GridCoordinate):
    """ represents a region spanning multiple Tiles in a worldwide grid of Regions. """

    def __init__(self, zoom, x, y, log_tiles_per_row=0):
        """
        Build a region containing multiple tiles.

        A region is a square containing multiple tiles, e.g.
                 -- --
                | 1| 2|
                 -- --
                | 3| 4|
                 -- --
        A region must contain at least one tile and each row must have
        a power of two of tiles. The size of the region is specified
        with log2(tiles per row per region), e.g.
            * log_tiles_per_row = 0 means 2**0 = 1 tile
            * log_tiles_per_row = 2 means 2**2 = 4 tiles per row, thus 16 tiles per region.

        Args:
            zoom (int): clear.
            x (int): clear.
            y (int): clear.
            log_tiles_per_row (int): size of the region as log2(tiles per row per region).
                needs to be at least 0 (-> 1 tile) and at most 5 (-> 1024 tiles)
        """
        assert log_tiles_per_row in range(0, 5)
        super().__init__(zoom, x, y)
        self.log_tiles_per_row = log_tiles_per_row
        self.tiles_per_row = 2 ** log_tiles_per_row
        self.root_tile = TileCoordinate(zoom, x * self.tiles_per_row, y * self.tiles_per_row)

    def geographic_bounds(self):
        p1 = self.root_tile.to_geographic()
        p2 = TileCoordinate(self.root_tile.zoom,
                            self.root_tile.x + self.tiles_per_row,
                            self.root_tile.y + self.tiles_per_row).to_geographic()
        return GeographicBB(p1.lon, p2.lat, p2.lon, p1.lat)

    def get_tiles(self):
        """Get all TileCoordinates contained in the region"""
        for x, y in griditer(self.root_tile.x, self.root_tile.y, ncol=self.tiles_per_row):
            yield TileCoordinate(self.root_tile.zoom, x, y)

    def zoom_in(self):
        for x, y in griditer(self.x * 2, self.y * 2, ncol=2):
            yield RegionCoordinate(self.zoom + 1, x, y, log_tiles_per_row=self.log_tiles_per_row)

    def __str__(self):
        return ("<zoom: " + str(self.zoom) + ", x: " + str(self.x) + ", y: " + str(self.y) +
                ", log_tiles_per_row: " + str(self.log_tiles_per_row) + ">")


class GridBB:
    """ A bounding box defined by two grid coordinates """

    def __init__(self, zoom, min_x, min_y, max_x, max_y):
        self.zoom = zoom
        self.min = GridCoordinate(zoom, min_x, min_y)
        self.max = GridCoordinate(zoom, max_x, max_y)

    def intersection(self, other):
        intersects = self.min.x <= other.max.x and self.max.x >= other.min.x and \
                     self.min.y <= other.max.y and self.max.y >= other.min.y
        if intersects:
            return GridBB(self.zoom,
                          max(self.min.x, other.min.x),
                          max(self.min.y, other.min.y),
                          min(self.max.x, other.max.x),
                          min(self.max.y, other.max.y))
        else:
            return []

    def intersections(self, other):
        intersections = []
        i = self.intersection(other)
        if i: intersections.append(i)
        if self.max.x >= 2 ** self.zoom:
            i = GridBB(self.zoom, 0, self.min.y, self.max.x % (2 ** self.zoom), self.max.y).intersection(other)
            if i: intersections.append(i)
        return intersections

    def is_inside(self, tile):
        return self.min.y <= tile.y <= self.max.y and \
               (self.min.x <= tile.x <= self.max.x or
                (self.max.x > 2 ** tile.zoom - 1 and
                 0 <= tile.x <= self.max.x % (2 ** tile.zoom)))

    def __str__(self):
        return "<tile min: " + str(self.min) + ", max: " + str(self.max) + ">"

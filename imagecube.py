# Licensed under a 3-clause BSD style license - see LICENSE.rst

# imagecube
# This package accepts FITS images from the user and delivers images that have been
# converted to the same flux units, registered to a common world coordinate system
# (WCS), convolved to a common resolution, and resampled to a common pixel scale
# requesting the Nyquist sampling rate.
# Each step can be run separately or as a whole.
# The user should provide us with information regarding wavelength, pixel scale,
# extension of the cube, instrument, physical size of the target, and WCS header 
# information.

# NOTETOSELF: make sure that the conventions at http://docs.astropy.org/en/latest/development/codeguide.html#standard-output-warnings-and-errors 
# are being followed. Maybe we can have a --verbose mode where extra
# information gets printed to stdout.

from __future__ import print_function, division

#things to import regarding pyraf & iraf

import pyraf
from pyraf import iraf
#the following line is to override the login.cl requirement of IRAF
iraf.set(uparm='.')

from iraf import noao, images
from iraf import artdata, immatch, imcoords

import sys
import getopt

import glob

import math

import os

from astropy.io import fits
from astropy.nddata import make_kernel, convolve
from astropy import units as u
from astropy import constants
import numpy as np

import scipy, pylab
from matplotlib import rc

import astropy.utils.console as console

NYQUIST_SAMPLING_RATE = 3.3
"""
Code constant: NYQUIST_SAMPLING_RATE

Some explanation of where this value comes from is needed.

"""

MJY_PER_SR_TO_JY_PER_PIXEL = 2.3504 * 10**(-5)
"""
Code constant: MJY_PER_SR_TO_JY_PER_PIXEL

Factor for converting Spitzer (MIPS and IRAC)  units from MJy/sr to
Jy/(pixel area)

"""

FUV_LAMBDA_CON = 1.40 * 10**(-15)
"""
Code constant: FUV_LAMBDA_CON

Calibration from CPS to Flux in [erg sec-1 cm-2 AA-1], as given in GALEX
for the FUV filter.
http://galexgi.gsfc.nasa.gov/docs/galex/FAQ/counts_background.html

"""

NUV_LAMBDA_CON = 2.06 * 10**(-16)
"""
Code constant: NUV_LAMBDA_CON

Calibration from CPS to Flux in [erg sec-1 cm-2 AA-1], as given in GALEX
for the NUV filter.
http://galexgi.gsfc.nasa.gov/docs/galex/FAQ/counts_background.html

"""

FVEGA_J = 1594
"""
Code constant: FVEGA_J

Flux value (in Jy) of Vega for the 2MASS J filter.

"""

FVEGA_H = 1024
"""
Code constant: FVEGA_H

Flux value (in Jy) of Vega for the 2MASS H filter.

"""

FVEGA_KS = 666.7
"""
Code constant: FVEGA_KS

Flux value (in Jy) of Vega for the 2MASS Ks filter.

"""

WAVELENGTH_2MASS_J = 1.2409
"""
Code constant: WAVELENGTH_2MASS_J

Representative wavelength (in micron) for the 2MASS J filter

"""

WAVELENGTH_2MASS_H = 1.6514
"""
Code constant: WAVELENGTH_2MASS_H

Representative wavelength (in micron) for the 2MASS H filter

"""

WAVELENGTH_2MASS_KS = 2.1656
"""
Code constant: WAVELENGTH_2MASS_KS

Representative wavelength (in micron) for the 2MASS Ks filter

"""

#JY_CONVERSION = 10**23
JY_CONVERSION = u.Jy.to(u.erg / u.cm**2 / u.s / u.Hz, 1., equivalencies=u.spectral_density(u.AA, 1500))  ** -1
"""
Code constant: JY_CONVERSION

This is to convert the GALEX flux units given in erg/s/cm^2/Hz to Jy.

"""

S250_BEAM_AREA = 423
"""
Code constant: S250_BEAM_AREA

Beam area (arcsec^2) for SPIRE 250 band.
From SPIRE Observer's Manual v2.4.

"""
S350_BEAM_AREA = 751
"""
Code constant: S250_BEAM_AREA

Beam area (arcsec^2) for SPIRE 350 band.
From SPIRE Observer's Manual v2.4.

"""
S500_BEAM_AREA = 1587
"""
Code constant: S500_BEAM_AREA

Beam area (arcsec^2) for SPIRE 500 band.
From SPIRE Observer's Manual v2.4.

"""

def is_number(s):
    """
    Checks whether the input value is a number or not.

    Parameters
    ----------
    s
        The value to check

    Returns
    -------
    Boolean
        True if s is a number, False otherwise
    """

    try:
        float(s)
        return True
    except ValueError:
        return False

def print_usage():
    """
    Displays usage information in case of a command line error.
    """

    print("""
Usage: """ + sys.argv[0] + """ --dir <directory> --ang_size <angular_size> [--flux_conv] [--im_reg] [--im_ref <filename>] [--im_conv] [--fwhm <fwhm value>] [--im_regrid] [--seds] [--cleanup] [--help]  

dir: the path to the directory containing the <input FITS files> to be 
processed

ang_size: the angular size of the object in arcsec

flux_conv: if flux units are not in Jy/pixel, this task will perform unit
conversion to Jy/pixel.
NOTE: If data are not GALEX, 2MASS, MIPS, IRAC, PACS, SPIRE, then the user
should provide flux unit conversion factors to go from the image's native
flux units to Jy/pixel. This information should be recorded in the header
keyword FLUXCONV for each input image.

im_reg: it performs the registration of the input images to the reference
image. The user should provide the reference image with the im_ref 
parameter.

im_ref: this is a reference image the user provides. In the header, the following keywords should be present: CRVAL1, CRVAL2, which give the RA and DEC to which the images will be registered using im_reg.

im_conv: it performs convolution to a common resolution, either Gaussian
or using a PSF kernel. The user provides the angular
resolution with the fwhm parameter. If the PSF kernel is chosen, the user provides
the PSF kernels with the following naming convention:

    <input FITS files>_kernel.fits

For example: an input image named SI1.fits will have a corresponding
kernel file named SI1_kernel.fits

fwhm: the user provides the angular resolution in arcsec to which all images will be convolved with im_conv

im_regrid: it performs regridding of the convolved images to a common
pixel scale. The pixel scale is defined to be the fwhm divided by """ + `NYQUIST_SAMPLING_RATE` + """.

seds: it produces the spectral energy distribution on a pixel-by-pixel
basis, on the regridded images.

cleanup: if this parameter is present, then output files from previous 
executions of the script are removed and no processing is done.

help: if this parameter is present, this message will be displayed and no 
processing will be done.

NOTE: the following keywords must be present, along with a comment containing the units (where applicable), for optimal image processing:
    CRVAL1: it contains the RA (in degrees) to which the images will be registered by im_reg
    CRVAL2: it contains the DEC (in degrees) to which the images will be registered by im_reg
    WAVELNTH: the representative wavelength (in micrometres) of the filter bandpass
    CDELT1: the pixelscale (in degrees) along the x-axis
    CDELT2: the pixelscale (in degrees) along the y-axis
If any of these keywords are missing, imagecube will attempt to determine them 
as best as possible. The calculated values will be present in the headers of 
the output images; if they look wrong, please check the headers of your input 
images and make sure that these values are present.
    """)

# NOTETOSELF: Other acceptable units: mm, m, Hz
def wavelength_to_microns(wavelength, unit):
    """
    Converts the input wavelength units into microns so that we only have
    to deal with a single unit.

    Parameters
    ----------
    wavelength:
        The wavelength.
    unit:
        The original unit of the wavelength.

    Returns
    -------
    return_value: float
        The wavelength in microns.
    """

    if (unit in u.micron.names or unit in u.um.names):
        return_value = float(wavelength)
    elif (unit in u.angstrom.names):
        return_value = u.angstrom.to(u.micron, float(wavelength))
    # This is a placeholder default value for now - it is not intended to be used
    # for real!
    # NOTETOSELF: That means that some proper error checking needs to be done here.
    else:
        return_value = 1

    return return_value

# NOTETOSELF: other keywords may be acceptable
# NOTETOSELF: pass the filenames to this function as well so we know which file we are
# on in case of problems.
# NOTETOSELF: proper error checking needed.
def get_instrument(header):
    """
    Determines which instrument the data in a FITS file came from.
    This is done by checking certain keywords in the FITS header.

    Parameters
    ----------
    header: FITS file header
        The header of the FITS file to be checked.

    Returns
    -------
    instrument: string
        The instrument which the data in the FITS file came from.
    """
    instrument = ''
    # Check for INSTRUME keyword first
    if ('INSTRUME' in header):
        instrument = header['INSTRUME']
    # Then check for 'galex' in the INF0001 keyword
    elif ('INF0001' in header):
        if ('galex' in header['INF0001']):
            instrument = 'GALEX'
    # Finally, check to see if the 'ORIGIN' keyword has a value of '2MASS'
    elif ('ORIGIN' in header):
        if ('2MASS' in header['ORIGIN']):
        #if (header['ORIGIN'] == '2MASS'):
            instrument = '2MASS'
    else:
        print("could not determine instrument; please insert appropriate information in the header.")
        sys.exit()

    return instrument

# NOTETOSELF: this value should be returned in arcsec, so some additional checking will
# be needed to ensure that the proper units are being used.
def get_native_pixelscale(header, instrument):
    """
    Returns the native pixelscale of the given instrument. Depending on the
    instrument, the pixelscale can be located in different header keywords.

    Parameters
    ----------
    header: FITS file header
        The header of the FITS file to be checked.

    instrument: string
        The instrument which the data in the FITS file came from

    Returns
    -------
    pixelscale: float
        The native pixelscale of the given instrument.
    """

    pixelscale = 0
    if (instrument == 'IRAC'):
        pixelscale = abs(header['PXSCAL1'])
    elif (instrument == 'MIPS'):
        pixelscale = header['PLTSCALE']
    elif (instrument == 'SPIRE'):
        pixelscale = u.deg.to(u.arcsec, abs(header['CDELT2']))
    else:
        if ('CDELT2' in header):
            pixelscale = u.deg.to(u.arcsec, abs(header['CDELT2']))

    if (pixelscale == 0):
        print("The native pixelscale is 0, so something may have gone wrong here.")

    return pixelscale


# NOTETOSELF: if the instrument is not found, the user can provide the value themselves
def get_conversion_factor(header, instrument):
    """
    Returns the factor that is necessary to convert an image's native "flux 
    units" to Jy/pixel.

    Parameters
    ----------
    header: FITS file header
        The header of the FITS file to be checked.

    instrument: string
        The instrument which the data in the FITS file came from

    Returns
    -------
    conversion_factor: float
        The conversion factor that will convert the image's native "flux
        units" to Jy/pixel.
    """

    # Give a default value that can't possibly be valid; if this is still the value
    # after running through all of the possible cases, then an error has occurred.
    conversion_factor = 0

    if (instrument == 'IRAC'):
        pixelscale = get_native_pixelscale(header, 'IRAC')
        #print("Pixel scale: " + `pixelscale`)
        # NOTEOTSELF: This is a hardcoded value from what Sophia gave me.
        # I would like to see if we could also obtain this from units.
        # The native "flux unit" is MJy/sr and we convert it to Jy/pixel
        conversion_factor = (MJY_PER_SR_TO_JY_PER_PIXEL) * (pixelscale**2)

    elif (instrument == 'MIPS'):
        pixelscale = get_native_pixelscale(header, 'MIPS')
        #print("Pixel scale: " + `pixelscale`)
        conversion_factor = (MJY_PER_SR_TO_JY_PER_PIXEL) * (pixelscale**2)

    elif (instrument == 'GALEX'):
        wavelength = u.um.to(u.angstrom, header['WAVELENG'])
        #print("Speed of light: " + `constants.c.to('um/s').value`)
        f_lambda_con = 0
        # I am using a < comparison here to account for the possibility that the given
        # wavelength is not EXACTLY 1520 AA or 2310 AA
        if (wavelength < 2000): 
            f_lambda_con = FUV_LAMBDA_CON
        else:
            f_lambda_con = NUV_LAMBDA_CON
        conversion_factor = ((JY_CONVERSION) * f_lambda_con * wavelength**2) / (constants.c.to('angstrom/s').value)
        #print("lambda^2/c = " + `(wavelength**2) / (constants.c.to('angstrom/s').value)`)

    # This calculation comes from the definition of the magnitude system.
    elif (instrument == '2MASS'):
        #print("MAGZP: " + `header['MAGZP']`)
        fvega = 0
        if (header['FILTER'] == 'j'):
            fvega = FVEGA_J
        elif (header['FILTER'] == 'h'):
            fvega = FVEGA_H
        elif (header['FILTER'] == 'k'):
            fvega = FVEGA_KS
        conversion_factor = fvega * 10**(-0.4 * header['MAGZP'])

    elif (instrument == 'PACS'):
        # Confirm that the data is already in Jy/pixel by checking the BUNIT header
        # keyword
        if ('BUNIT' in header):
            if (header['BUNIT'].lower() != 'jy/pixel'):
                # NOTETOSELF: ask for more input here if necessary
                print("Instrument is PACS, but Jy/pixel is not being used in BUNIT.")
        conversion_factor = 1;

    elif (instrument == 'SPIRE'):
        pixelscale = get_native_pixelscale(header, 'SPIRE')
        wavelength = header['WAVELENG']
        if (wavelength == 250):
            conversion_factor = (pixelscale**2) / S250_BEAM_AREA
        elif (wavelength == 350):
            conversion_factor = (pixelscale**2) / S350_BEAM_AREA
        elif (wavelength == 500):
            conversion_factor = (pixelscale**2) / S500_BEAM_AREA
    
    return conversion_factor

# NOTETOSELF: I wonder if it might be best to force a type on the wavelength - e.g.
# float - so that this doesn't have to be done later by other functions.
# NOTETOSELF: proper error checking - e.g. the wavelength should not actually end up
# as 0 after all the cases have been checked.
# NOTETOSELF: Would it be best to force the units to be microns? Check to see how this
# would impact other functions first.
def get_wavelength(header):
    """
    Returns the wavelength and its units for a given FITS image.

    Parameters
    ----------
    header: FITS file header
        The header of the FITS file to be checked.

    Returns
    -------
    wavelength:
        The wavelength value for the given FITS image.
    wavelength_units: string
        The units of the wavelength (generally microns, but can be other
        units as well).
    """

    wavelength = 0
    wavelength_units = ''
    if ('WAVELENG' in header):
        wavelength = header['WAVELENG']
        wavelength_units = header.comments['WAVELENG']
    elif ('WAVELNTH' in header):
        # NOTETOSELF: microns are not necessarily used here - check the header comments
        wavelength = header['WAVELNTH']
        wavelength_units = 'micron'
    elif ('FILTER' in header):
        # NOTETOSELF: Check the actual instrument to make sure that this should be in
        # microns.
        wavelength = header['FILTER']
        instrument = get_instrument(header)
        if (instrument == '2MASS'):
            if (header['FILTER'].lower() == 'j'):
                wavelength = WAVELENGTH_2MASS_J
            elif (header['FILTER'].lower() == 'h'):
                wavelength = WAVELENGTH_2MASS_H
            elif (header['FILTER'].lower() == 'k'):
                wavelength = WAVELENGTH_2MASS_KS
        wavelength_units = 'micron'

    return wavelength, wavelength_units

def wavelength_range(wavelengths, lower, upper):
    """
    Determines if the provided list of wavelengths contains a value
    between the given lower and upper bounds.

    Parameters
    ----------
    wavelengths: list
        A list of wavelength values.
    lower: float
        The lower bound to check.
    upper: float
        The upper bound to check.

    Returns
    -------
    return_value: boolean
        True if there is a value in the list of wavelengths that is
        between the lower and upper bounds; False otherwise.
    """

    return_value = False
    for i in wavelengths:
        if (i >= lower and i <= upper):
            return_value = True
    return return_value

# NOTETOSELF: Sophia will be providing proper wavelength ranges to check here.
def get_fwhm_value(images_with_headers):
    """
    Determines the fwhm value given the instrument and wavelength values
    that are present in all of the input images.
    This function depends on data taken from Aniano et al. 2011.

    Parameters
    ----------
    images_with_headers: zipped list structure
        A structure containing headers and image data for all FITS input
        images.

    Returns
    -------
    fwhm: float
        The fwhm value.
    """

    fwhm = 0
    instruments = []
    instruments_with_wavelengths = {}
    # Determine which instruments and wavelengths we have data from
    # This is done by creating a dictionary with instruments as the keys,
    # and a list of wavelengths from each instrument as values.
    for i in range(0, len(images_with_headers)):
        instrument = get_instrument(images_with_headers[i][1])
        # The [0] is here because we only need the wavelength, not the units as well.
        wavelength = get_wavelength(images_with_headers[i][1])[0]
        if (instrument in instruments_with_wavelengths):
            instruments_with_wavelengths[instrument].append(wavelength)
        else:
            instruments_with_wavelengths[instrument] = [wavelength]

    if ('MIPS' in instruments_with_wavelengths and wavelength_range(instruments_with_wavelengths['MIPS'], 140, 170)):
        fwhm = 76
    elif ('SPIRE' in instruments_with_wavelengths and wavelength_range(instruments_with_wavelengths['SPIRE'], 490, 510)):
        fwhm = 43
    elif ('MIPS' in instruments_with_wavelengths and wavelength_range(instruments_with_wavelengths['MIPS'], 50, 90)):
        fwhm = 37
    elif ('SPIRE' in instruments_with_wavelengths and wavelength_range(instruments_with_wavelengths['SPIRE'], 300, 400)):
        fwhm = 30
    elif ('SPIRE' in instruments_with_wavelengths and wavelength_range(instruments_with_wavelengths['SPIRE'], 200, 299)):
        fwhm = 22
    elif ('PACS' in instruments_with_wavelengths and wavelength_range(instruments_with_wavelengths['PACS'], 140, 180)):
        fwhm = 18
    elif ('MIPS' in instruments_with_wavelengths and wavelength_range(instruments_with_wavelengths['MIPS'], 18, 30)):
        fwhm = 13
    elif ('PACS' in instruments_with_wavelengths and wavelength_range(instruments_with_wavelengths['PACS'], 90, 110)):
        fwhm = 12.5
    elif ('PACS' in instruments_with_wavelengths and wavelength_range(instruments_with_wavelengths['PACS'], 60, 80)):
        fwhm = 10.5

    return fwhm

def parse_command_line():
    """
    Parses the command line to obtain parameters.

    """

    global phys_size
    global directory
    global conversion_factors
    global do_conversion
    global do_registration
    global do_convolution
    global do_resampling
    global do_seds
    global do_cleanup
    global ra_input
    global dec_input
    global main_reference_image
    global convolution_reference_image

    try:
        opts, args = getopt.getopt(sys.argv[1:], "", ["directory=", "angular_size=", "conversion_factors", "conversion", "registration", "convolution", "resampling", "seds", "cleanup", "ra=", "dec=", "reference_image=", "convolution_reference_image=", "help"])
    except getopt.GetoptError:
        print("An error occurred. Check your parameters and try again.")
        sys.exit(2)
    for opt, arg in opts:
        if opt in ("--help"):
            print_usage()
            sys.exit()
        if opt in ("--angular_size"):
            phys_size = float(arg)
        if opt in ("--directory"):
            directory = arg
            if (not os.path.isdir(directory)):
                print("Error: The directory cannot be found: " + directory)
                sys.exit()
        if opt in ("--conversion_factors"):
            conversion_factors = True
        if opt in ("--conversion"):
            do_conversion = True
        if opt in ("--registration"):
            do_registration = True
        if opt in ("--convolution"):
            do_convolution = True
        if opt in ("--resampling"):
            do_resampling = True
        if opt in ("--seds"):
            do_seds = True
        if opt in ("--cleanup"):
            do_cleanup = True
        if opt in ("--ra"):
            ra_input = float(arg)
        if opt in ("--dec"):
            dec_input = float(arg)
        if opt in ("--reference_image"):
            main_reference_image = arg
        if opt in ("--convolution_reference_image"):
            convolution_reference_image = arg

    if (main_reference_image != ''):
        try:
            with open(directory + '/' + main_reference_image): pass
        except IOError:
            print("The file " + main_reference_image + " could not be found in the directory " + directory)
            sys.exit()

    if (convolution_reference_image != ''):
        try:
            with open(directory + '/' + convolution_reference_image): pass
        except IOError:
            print("The file " + convolution_reference_image + " could not be found in the directory " + directory)
            sys.exit()

def output_conversion_factors(images_with_headers):
    """
    Prints a formatted list of instruments, wavelengths, and conversion
    factors to Jy/pixel

    Parameters
    ----------
    images_with_headers: zipped list structure
        A structure containing headers and image data for all FITS input
        images.

    """

    print("Instrument\tWavelength\tConversion factor (to Jy/pixel)")
    for i in range(0, len(images_with_headers)):
        wavelength = images_with_headers[i][1]['WAVELENG']
        wavelength_units = images_with_headers[i][1].comments['WAVELENG']
        instrument = get_instrument(images_with_headers[i][1])
        conversion_factor = get_conversion_factor(images_with_headers[i][1], instrument)
        print(instrument + '\t' + `wavelength` + '\t' + `conversion_factor`)

def convert_images(images_with_headers):
    """
    Converts all of the input images' native "flux units" to Jy/pixel
    The converted values are stored in the list of arrays, 
    converted_data, and they are also saved as new FITS images.

    Parameters
    ----------
    images_with_headers: zipped list structure
        A structure containing headers and image data for all FITS input
        images.

    """

    print("Converting images")
    for i in range(0, len(images_with_headers)):
        instrument = get_instrument(images_with_headers[i][1])
        conversion_factor = get_conversion_factor(images_with_headers[i][1], instrument)

        # Some manipulation of filenames and directories
        original_filename = os.path.basename(images_with_headers[i][2])
        original_directory = os.path.dirname(images_with_headers[i][2])
        new_directory = original_directory + "/converted/"
        converted_filename = new_directory + original_filename  + "_converted.fits"
        if not os.path.exists(new_directory):
            os.makedirs(new_directory)

        # Do a Jy/pixel unit conversion and save it as a new .fits file
        converted_data_array = images_with_headers[i][0] * conversion_factor
        converted_data.append(converted_data_array)
        images_with_headers[i][1]['BUNIT'] = 'Jy/pixel'
        images_with_headers[i][1]['JYPXFACT'] = (conversion_factor, 'Factor to convert original BUNIT into Jy/pixel.')
        hdu = fits.PrimaryHDU(converted_data_array, images_with_headers[i][1])
        print("Creating " + converted_filename)
        hdu.writeto(converted_filename, clobber=True)

def get_herschel_mean(images_with_headers, keyword):
    """
    Checks all of the FITS images with data from Herschel instruments
    (currently PACS and SPIRE) and returns the mean value of the given
    FITS header keyword from all the relevant images.

    Parameters
    ----------
    images_with_headers: zipped list structure
        A structure containing headers and image data for all FITS input
        images.
    keyword: string
        The header keyword for which the mean value will be calculated.

    Returns
    -------
    return_value: float
        The mean of the values of the given header keyword for all images
        with data from Herschel instruments.
    """

    print("get_herschel_mean(" + keyword + ")")
    values = []
    return_value = 0
    for i in range(0, len(images_with_headers)):
        instrument = get_instrument(images_with_headers[i][1])
        if (instrument == 'PACS' or instrument == 'SPIRE'):
            value = images_with_headers[i][1][keyword]
            values.append(value)
    return_value = np.mean(values)
    return return_value

# NOTETOSELF: try to do this from the converted_data array first.
# If that fails, then we can always just read in the _converted.fits files that were
# also created by convert_images().
# NOTETOSELF: Sophia told me that we need the single RA/dec value that gets used
# later (in the resampling step, I believe) in this step as well.
def register_images(images_with_headers):
    """
    Registers all of the images to a common WCS

    Parameters
    ----------
    images_with_headers: zipped list structure
        A structure containing headers and image data for all FITS input
        images.

    """

    print("Registering images")
    print("phys_size: " + `phys_size`)

    if (ra_input != ''):
        lngref_input = ra_input
    else:
        lngref_input = get_herschel_mean(images_with_headers, 'CRVAL1')

    if (dec_input != ''):
        latref_input = dec_input
    else:
        latref_input = get_herschel_mean(images_with_headers, 'CRVAL2')

    for i in range(0, len(images_with_headers)):

        native_pixelscale = get_native_pixelscale(images_with_headers[i][1], get_instrument(images_with_headers[i][1]))
        print("Native pixel scale: " + `native_pixelscale`)
        print("Instrument: " + `get_instrument(images_with_headers[i][1])`)
        print("BUNIT: " + `images_with_headers[i][1]['BUNIT']`)

        original_filename = os.path.basename(images_with_headers[i][2])
        original_directory = os.path.dirname(images_with_headers[i][2])
        new_directory = original_directory + "/registered/"
        artificial_filename = new_directory + original_filename + "_pixelgrid.fits"
        registered_filename = new_directory + original_filename  + "_registered.fits"
        input_directory = original_directory + "/converted/"
        input_filename = input_directory + original_filename  + "_converted.fits"
        print("Artificial filename: " + artificial_filename)
        print("Registered filename: " + registered_filename)
        print("Input filename: " + input_filename)
        if not os.path.exists(new_directory):
            os.makedirs(new_directory)

        # First we create an artificial fits image
        # unlearn some iraf tasks
        iraf.unlearn('mkpattern')

        # create an artificial image to which we will register the FITS image.
        artdata.mkpattern(input=artificial_filename, output=artificial_filename, pattern="constant", pixtype="double", ndim=2, ncols=phys_size/native_pixelscale, nlines=phys_size/native_pixelscale)
        #note that in the exact above line, the "ncols" and "nlines" should be wisely chosen, depending on the input images - they provide the pixel-grid 
        #for each input fits image, we will create the corresponding artificial one - therefore we can tune these values such that we cover, for instance, XXarcsecs of the target - so the best is that user provides us with such a value

        # Then, we tag the desired WCS in this fake image:
        # unlearn some iraf tasks
        iraf.unlearn('ccsetwcs')

        # tag the desired WCS in the artificial image.
        iraf.ccsetwcs(images=artificial_filename, database="", solution="", xref=(phys_size/native_pixelscale)/2, yref=(phys_size/native_pixelscale)/2, xmag=native_pixelscale, ymag=native_pixelscale, xrotati=0.,yrotati=0.,lngref=lngref_input, latref=latref_input, lngunit="degrees", latunit="degrees", transpo="no", project="tan", coosyst="j2000", update="yes", pixsyst="logical", verbose="yes")
        #note that the "xref" and "yref" are actually half the above "ncols", "nlines", respectively, so that we center each image
        #note also that "xmag" and "ymag" is the pixel-scale, which in the current step ought to be the same as the native pixel-scale of the input image, for each input image - so we check the corresponding header value in each image
        #note that "lngref" and "latref" can be grabbed by the fits header, it is actually the center of the target (e.g. ngc1569)
        #note that we should make sure that the coordinate system is in coosyst="j2000" by checking the header info, otherwise we need to adjust that

        # Then, register the fits file of interest to the WCS of the fake fits file
        # unlearn some iraf tasks
        iraf.unlearn('wregister')

        # register the science fits image
        iraf.wregister(input=input_filename, reference=artificial_filename, output=registered_filename, fluxconserve="no")

# NOTETOSELF: This function requires a PSF kernel. Not sure where it should go, but
# here it is just in case we still need it. It is NOT ready to be run yet.
def convolve_images_psf(images_with_headers):
    print("Convolving images (not implemented yet)")

    for i in range(0, len(images_with_headers)):

        original_filename = os.path.basename(images_with_headers[i][2])
        original_directory = os.path.dirname(images_with_headers[i][2])
        new_directory = original_directory + "/convolved/"
        #artificial_filename = new_directory + original_filename + "_pixelgrid.fits"
        #registered_filename = new_directory + original_filename  + "_registered.fits"
        input_directory = original_directory + "/registered/"
        input_filename = input_directory + original_filename  + "_registered.fits"
        print("Artificial filename: " + artificial_filename)
        print("Registered filename: " + registered_filename)
        print("Input filename: " + input_filename)
        if not os.path.exists(new_directory):
            os.makedirs(new_directory)

        #reading the science image:
        science_image = fits.getdata(input_filename)

        # if using a kernel image, then we first regrid the kernel to the same as in the science image, and we re-center the kernel:

        # create a fake image "apixel_kernel.fits"
        # the original kernel has a grid of 3645*3645 pixels and centered at (1822, 1822)
        # ncols = nlines = initial_number_of_rows * initial_pixelsize_of_the_kernel  / science_image_pixelsize
        # in the current case: 3645* 0.25 (arcsecs per pixel) / 2 (arcsecs per pixel) = 455.62
        artdata.mkpattern(input="apixel_kernel.fits", output="apixel_kernel.fits", pattern="constant", option="replace",v1=0., v2=1., size=1, title="", pixtype="real", ndim=2, ncols=455,nlines=455,n3=1, n4=1, n5=1, n6=1, n7=1, header="")

        #Then, tag the desired WCS in this fake image:
        #
        # unlearn some iraf tasks
        iraf.unlearn('ccsetwcs')
        #xref = yref = ncols/2 = nlines/2
        #xmag, ymag = pixel scale of science image
        iraf.ccsetwcs(images="apixel_kernel.fits", database="", solution="", xref=227.5, yref=227.5, xmag=2, ymag=2, xrotati=0.,yrotati=0.,lngref=0, latref=0, lngunit="hours", latunit="degrees", transpo="no", project="tan", coosyst="j2000", update="yes", pixsyst="logical", verbose="yes")

        # Then, register the fits file of interest to the WCS of the fake fits file
        #
        # unlearn some iraf tasks
        iraf.unlearn('wregister')

        iraf.wregister(input="Kernel_HiRes_PACS_70_to_SPIRE_500.fits", reference="apixel_kernel.fits", output="Kernel_P70_2_S500.fits", fluxconserve="yes")

        # then we get the data from the kernel
        kernel_image = pyfits.getdata('Kernel_P70_2_S500.fits')

        #several ways to do the convolution, but is best to use number 3 or 4:

        #3. 
        result3 = astropy.nddata.convolution.convolve.convolve(science_image, kernel_image) # got a segmentation fault - it needs an odd number of columns/rows for the kernel
        pyfits.writeto('science_image_convolved_3.fits',result3)

        #4. 
        result4 = astropy.nddata.convolution.convolve.convolve_fft(science_image,kernel_image) # worked OK - was the fastest thus far
        pyfits.writeto('science_image_convolved_4.fits',result4) 

def convolve_images(images_with_headers):
    """
    Convolves all of the images to a common resolution using a simple
    gaussian kernel.

    Parameters
    ----------
    images_with_headers: zipped list structure
        A structure containing headers and image data for all FITS input
        images.

    """

    print("Convolving images")
    fwhm_input = get_fwhm_value(images_with_headers)
    print("fwhm_input = " + `fwhm_input`)

    for i in range(0, len(images_with_headers)):

        native_pixelscale = get_native_pixelscale(images_with_headers[i][1], get_instrument(images_with_headers[i][1]))
        sigma_input = fwhm_input / (2* math.sqrt(2*math.log (2) ) * native_pixelscale)
        print("Native pixel scale: " + `native_pixelscale`)
        print("Instrument: " + `get_instrument(images_with_headers[i][1])`)

        original_filename = os.path.basename(images_with_headers[i][2])
        original_directory = os.path.dirname(images_with_headers[i][2])
        new_directory = original_directory + "/convolved/"
        convolved_filename = new_directory + original_filename  + "_convolved.fits"
        input_directory = original_directory + "/registered/"
        input_filename = input_directory + original_filename  + "_registered.fits"
        print("Convolved filename: " + convolved_filename)
        print("Input filename: " + input_filename)
        if not os.path.exists(new_directory):
            os.makedirs(new_directory)

        # NOTETOSELF: there has been a loss of data from the data cubes at an earlier
        # step. The presence of 'EXTEND' and 'DSETS___' keywords in the header no
        # longer means that there is any data in hdulist[1].data. I am using a
        # workaround for now, but this needs to be looked at.
        hdulist = fits.open(input_filename)
        header = hdulist[0].header
        image_data = hdulist[0].data
        #if ('EXTEND' in header and 'DSETS___' in header):
            #image_data = hdulist[1].data
        #else:
            #image_data = hdulist[0].data
        hdulist.close()

        gaus_kernel_inp = make_kernel([3,3], kernelwidth=sigma_input, kerneltype='gaussian', trapslope=None, force_odd=True)

        # Do the convolution and save it as a new .fits file
        conv_result = convolve(image_data, gaus_kernel_inp)
        header['FWHM'] = (fwhm_input, 'The FWHM value used in the convolution step.')

        hdu = fits.PrimaryHDU(conv_result, header)
        print("Creating " + convolved_filename)
        hdu.writeto(convolved_filename, clobber=True)

def create_data_cube(images_with_headers):
    """
    Creates a data cube from the provided images.


    Parameters
    ----------
    images_with_headers: zipped list structure
        A structure containing headers and image data for all FITS input
        images.

    Notes
    -----
    Currently we are just using the header of the first input image.
    This should be changed to something more appropriate.
    """
    print("Creating a data cube.")
    resampled_images = []
    resampled_headers = []

    new_directory = directory + "/datacube/"
    print("New directory: " + new_directory)
    if not os.path.exists(new_directory):
        os.makedirs(new_directory)

    for i in range(0, len(images_with_headers)):
        original_filename = os.path.basename(images_with_headers[i][2])
        original_directory = os.path.dirname(images_with_headers[i][2])
        resampled_filename = original_directory + "/resampled/" + original_filename  + "_resampled.fits"

        hdulist = fits.open(resampled_filename)
        header = hdulist[0].header
        resampled_headers.append(header)
        image = hdulist[0].data
        resampled_images.append(image)
        hdulist.close()

    fits.writeto(new_directory + '/' + 'datacube.fits', np.copy(resampled_images), resampled_headers[0], clobber=True)

def resample_images(images_with_headers):
    """
    Resamples all of the images to a common pixel grid.

    Parameters
    ----------
    images_with_headers: zipped list structure
        A structure containing headers and image data for all FITS input
        images.

    """

    print("Resampling images.")

    # First we create an artificial fits image, 
    # The difference with the registration step is that the artificial image is now created only once, and it is common for all the input_images_convolved (or imput_images_gaussian_convolved)
    # unlearn some iraf tasks
    iraf.unlearn('mkpattern')
    
    # create a fake image "grid_final_resample.fits", to which we will register all fits images
    fwhm_input = get_fwhm_value(images_with_headers)
    print("fwhm: " + `fwhm_input`)
    # parameter1 & parameter2 depend on the "fwhm" of the convolution step, and following the Nyquist sampling rate. 
    parameter1 = phys_size / (fwhm_input / NYQUIST_SAMPLING_RATE) 
    print("ncols, nlines: " + `parameter1`)
    parameter2 = parameter1
    artdata.mkpattern(input="grid_final_resample.fits", output="grid_final_resample.fits", pattern="constant", pixtype="double", ndim=2, ncols=parameter1, nlines=parameter2)

    if (ra_input != ''):
        lngref_input = ra_input
    else:
        lngref_input = get_herschel_mean(images_with_headers, 'CRVAL1')
    if (dec_input != ''):
        latref_input = dec_input
    else:
        latref_input = get_herschel_mean(images_with_headers, 'CRVAL2')
    
    # Then, we tag the desired WCS in this fake image:
    # unlearn some iraf tasks
    iraf.unlearn('ccsetwcs')

    # tag the desired WCS in the fake image "apixel.fits"
    # NOTETOSELF: in the code Sophia gave me, lngunit was given as "hours", but I have
    # changed it to "degrees".
    iraf.ccsetwcs(images="grid_final_resample.fits", database="", solution="", xref=parameter1/2, yref=parameter2/2, xmag=fwhm_input/NYQUIST_SAMPLING_RATE, ymag=fwhm_input/NYQUIST_SAMPLING_RATE, xrotati=0.,yrotati=0.,lngref=lngref_input, latref=latref_input, lngunit="degrees", latunit="degrees", transpo="no", project="tan", coosyst="j2000", update="yes", pixsyst="logical", verbose="yes")

    for i in range(0, len(images_with_headers)):
        original_filename = os.path.basename(images_with_headers[i][2])
        original_directory = os.path.dirname(images_with_headers[i][2])
        new_directory = original_directory + "/resampled/"
        resampled_filename = new_directory + original_filename  + "_resampled.fits"
        input_directory = original_directory + "/convolved/"
        input_filename = input_directory + original_filename  + "_convolved.fits"
        print("Resampled filename: " + resampled_filename)
        print("Input filename: " + input_filename)
        if not os.path.exists(new_directory):
            os.makedirs(new_directory)

        # Then, register the fits file of interest to the WCS of the fake fits file
        # unlearn some iraf tasks
        iraf.unlearn('wregister')

        # register the science fits image
        iraf.wregister(input=input_filename, reference="grid_final_resample.fits", output=resampled_filename, fluxconserve="yes")

    create_data_cube(images_with_headers)

def output_seds(images_with_headers):
    """
    Makes the SEDs.

    Parameters
    ----------
    images_with_headers: zipped list structure
        A structure containing headers and image data for all FITS input
        images.

    """

    #print("Outputting SEDs.")

    all_image_data = []
    wavelengths = []

    num_wavelengths = len(images_with_headers)

    for i in range(0, num_wavelengths):
        original_filename = os.path.basename(images_with_headers[i][2])
        original_directory = os.path.dirname(images_with_headers[i][2])
        new_directory = original_directory + "/seds/"
        input_directory = original_directory + "/resampled/"
        input_filename = input_directory + original_filename  + "_resampled.fits"
        wavelength = get_wavelength(images_with_headers[i][1])[0]
        wavelengths.append(wavelength)
        #print("Input filename: " + input_filename)
        if not os.path.exists(new_directory):
            os.makedirs(new_directory)

        # Load the data for each image and append it to a master list of
        # all image data.
        hdulist = fits.open(input_filename)
        image_data = hdulist[0].data
        all_image_data.append(image_data)
        hdulist.close()

    sed_data = []

    for i in range(0, num_wavelengths):
        #print(`wavelengths[i]`)
        for j in range(len(all_image_data[i])):
            for k in range(len(all_image_data[i][j])):
                sed_data.append((int(j), int(k), wavelengths[i], all_image_data[i][j][k]))
                #print("(" + `j` + "," + `k` + ")" + '\t' + `all_image_data[i][j][k]` + ' ' + `wavelengths[i]`)

    #print(`sorted(sed_data)`)
    data = np.copy(sorted(sed_data))
    #np.savetxt('test.out', data, delimiter=',')
    np.savetxt('test.out', data, fmt='%d,%d,%f,%f', header='x, y, wavelength (um), flux units (Jy/pixel)')
    #print("len(data): " + `len(data)`)
    num_seds = int(len(data) / num_wavelengths)
    #print("Number of SEDs to create: " + `num_seds`)
    # just the wavelengths:
    #print(`data[:,2]`)
    # just the z-values:
    #print(`data[:,3]`)
    # for one wavelength:
    #print(`data[:,2][0:num_wavelengths]`)
    #print(`data[:,3][0:num_wavelengths]`)

    # for all wavelengths:
    with console.ProgressBarOrSpinner(num_seds, "Creating SEDs") as bar:
        for i in range(0, num_seds):
        #for i in range(0, 5):
            #print(`i`)

            # change to the desired fonts
            rc('font', family='Times New Roman')
            rc('text', usetex=True)
            
            # wavelength
            #a = data[:,2] 								
            wavelength_values = data[:,2][i*num_wavelengths:(i+1)*num_wavelengths]
            # flux
            #b = data[:,1]/1e20							
            #b = data[:,2]
            flux_values = data[:,3][i*num_wavelengths:(i+1)*num_wavelengths]
            #b = data[:,3][i:i+num_wavelengths]
            x_values = data[:,0][i*num_wavelengths:(i+1)*num_wavelengths]
            y_values = data[:,1][i*num_wavelengths:(i+1)*num_wavelengths]

            #print("\tx-values (" + `i*num_wavelengths` + "," + `(i+1)*num_wavelengths` + "): " + `x_values`)
            #print("\ty-values (" + `i*num_wavelengths` + "," + `(i+1)*num_wavelengths` + "): " + `y_values`)
            #print("\tWavelength (" + `i*num_wavelengths` + "," + `(i+1)*num_wavelengths` + "): " + `wavelength_values`)
            #print("\tFlux (" + `i*num_wavelengths` + "," + `(i+1)*num_wavelengths` + "): " + `flux_values`)

            #for w in range(0, num_wavelengths):
                #print(`x_values[w]` + "\t" + `y_values[w]` + "\t" + `wavelength_values[w]` + "\t" + `flux_values[w]`)

            # figure(1)
            pylab.figure(i)
            pylab.scatter(wavelength_values,flux_values)

            # axes specific
            pylab.xlabel(r'log(Wavelength) (um)')					
            pylab.ylabel(r'Flux (Jy/pixel)')
            pylab.rc('axes', labelsize=14, linewidth=2, labelcolor='black')
            pylab.semilogx()
            pylab.axis([min(wavelength_values),max(wavelength_values),min(flux_values),max(flux_values)])

            pylab.hold(True)

            # load the second data set
            #data2 = np.loadtxt('Te/SPEC_4.out', comments='%',usecols = (1,2)) 	
            #a2 = data2[:,0]
            #b2 = data2[:,1]/1e20

            # overplot in figure(1)
            #pylab.plot(a2,b2, 'r:',  markersize=3.0, linewidth=2.0, label='Te')	

            # load the third data set
            #data3 = np.loadtxt('Teff/SPEC_4.out', comments='%',usecols = (1,2)) 	
            #a3 = data3[:,0]
            #b3 = data3[:,1]/1e20

            # overplot in figure(1)
            #pylab.plot(a3,b3, 'b-.',  markersize=3.0, linewidth=2.0, label='Teff')	

            pylab.legend()
            pylab.savefig(new_directory + '/' + `int(x_values[0])` + '_' + `int(y_values[0])` + '_sed.eps')
            #pylab.show()
            bar.update(i)

def cleanup_output_files():
    """
    Removes files that have been generated by previous executions of the
    script.
    """

    print("Cleaning up output files.")

    import shutil

    for d in ('converted', 'registered', 'convolved', 'resampled', 'seds'):
        subdir = directory + '/' + d
        if (os.path.isdir(subdir)):
            print("Removing " + subdir)
            shutil.rmtree(subdir)

if __name__ == '__main__':
    phys_size = ''
    directory = ''
    ra_input = ''
    dec_input = ''
    main_reference_image = ''
    convolution_reference_image = ''
    conversion_factors = False
    do_conversion = False
    do_registration = False
    do_convolution = False
    do_resampling = False
    do_seds = False
    do_cleanup = False

    parse_command_line()

    if (do_cleanup):
        cleanup_output_files()
        sys.exit()

    # Grab all of the .fits and .fit files in the specified directory
    all_files = glob.glob(directory + "/*.fit*")

    # Lists to store information
    image_data = []
    converted_data = []
    registered_data = []
    convolved_data = []
    resampled_data = []
    headers = []
    filenames = []

    for i in all_files:
        hdulist = fits.open(i)
        #hdulist.info()
        header = hdulist[0].header
        # NOTETOSELF: The check for a data cube needs to be another function due to complexity. Check the
        # hdulist.info() values to see how much information is contained in the file.
        # In a data cube, there may be more than one usable science image. We need to make
        # sure that they are all grabbed.
        # Check to see if the input file is a data cube before trying to grab the image data
        if ('EXTEND' in header and 'DSETS___' in header):
            image = hdulist[1].data
        else:
            image = hdulist[0].data
        #filename = hdulist.filename()
        # Strip the .fit or .fits extension from the filename so we can append things to it
        # later on
        filename = os.path.splitext(hdulist.filename())[0]
        hdulist.close()
        #wavelength = header['WAVELENG']
        wavelength, wavelength_units = get_wavelength(header)
        #wavelength_units = header.comments['WAVELENG']
        wavelength_microns = wavelength_to_microns(wavelength, wavelength_units)
        #print("Wavelength " + `wavelength_microns` + "; Sample image value: " + `image[30][30]`)
        # NOTETOSELF: don't overwrite the header value here. Either create a new keyword,
        # say, WLMICRON, or include the original value in a comment.
        header['WAVELENG'] = (wavelength_microns, 'micron')
        image_data.append(image)
        headers.append(header)
        filenames.append(filename)

    # Sort the lists by their WAVELENG value
    images_with_headers_unsorted = zip(image_data, headers, filenames)
    images_with_headers = sorted(images_with_headers_unsorted, key=lambda header: header[1]['WAVELENG'])

    #if (conversion_factors):
        #output_conversion_factors(images_with_headers)

    if (do_conversion):
        convert_images(images_with_headers)

    if (do_registration):
        register_images(images_with_headers)

    if (do_convolution):
        convolve_images(images_with_headers)

    if (do_resampling):
        resample_images(images_with_headers)

    if (do_seds):
        output_seds(images_with_headers)

    sys.exit()

# imagecube
# This package accepts FITS images from the user and delivers images that have been
# converted to the same flux units, registered to a common world coordinate system
# (WCS), convolved to a common resolution, and resampled to a common pixel scale
# requesting the Nyquist sampling rate.
# Each step can be run separately or as a whole.
# The user should provide us with information regarding wavelength, pixel scale,
# extension of the cube, instrument, physical size of the target, and WCS header 
# information.

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

import os

from astropy.io import fits
from astropy.nddata import NDData
from astropy import units as u
from astropy import constants
import numpy as np

# Function: is_number(s)
# This function simply checks whether the input value is a number or not.
# It is used to check for proper input from the user.
def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False

# Function: print_usage()
# This function sisplays usage information in case of a command line error
def print_usage():
    print("Usage: " + sys.argv[0] + " --directory <directory> --angular_physical_size <angular_physical_size> [--conversion_factors]")
    print
    print("directory is the path to the directory containing FITS files to work with")
    print("angular_physical_size is the physical size to map to the object")
    print("conversion_factors will enable a formatted table of conversion factors to be output")

# Function: wavelength_to_microns(wavelength, unit)
# This function will convert the input wavelength units into microns so that we only
# have to deal with a single unit.
# NOTETOSELF: Other acceptable units: mm, m, Hz
def wavelength_to_microns(wavelength, unit):
    if (unit in u.micron.names or unit in u.um.names):
        return_value = float(wavelength)
    elif (unit in u.angstrom.names):
        return_value = u.angstrom.to(u.micron, float(wavelength))
    # This is a placeholder default value for now - it is not intended to be used
    # for real!
    else:
        return_value = 1

    return return_value

# Function: get_instruments(header)
# A function to determine which instrument was used. This is done by checking certain
# keywords in the FITS header.
# NOTETOSELF: other keywords may be acceptable
# NOTETOSELF: pass the filenames to this function as well so we know which file we are
# on in case of problems.
def get_instrument(header):
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
        if (header['ORIGIN'] == '2MASS'):
            instrument = '2MASS'
    else:
        print("could not determine instrument; please insert appropriate information in the header.")
        sys.exit()

    return instrument

# Function: get_conversion_factor(header, instrument)
# A function to obtain the factor that is necessary to convert an image's native "flux 
# units" to Jy/pixel.
# NOTETOSELF: if the instrument is not found, the user can provide the value themselves
def get_conversion_factor(header, instrument):
    # Give a default value that can't possibly be valid; if this is still the value
    # after running through all of the possible cases, then an error has occurred.
    conversion_factor = 0

    if (instrument == 'IRAC'):
        pixelscale = header['PXSCAL1']
        #print("Pixel scale: " + `pixelscale`)
        # NOTEOTSELF: This is a hardcoded value from what Sophia gave me.
        # I would like to see if we could also obtain this from units.
        # The native "flux unit" is MJy/sr and we convert it to Jy/pixel
        conversion_factor = (2.3504 * 10**(-5)) * (pixelscale**2)

    elif (instrument == 'MIPS'):
        pixelscale = header['PLTSCALE']
        #print("Pixel scale: " + `pixelscale`)
        conversion_factor = (2.3504 * 10**(-5)) * (pixelscale**2)

    elif (instrument == 'GALEX'):
        wavelength = u.um.to(u.angstrom, header['WAVELENG'])
        #print("Speed of light: " + `constants.c.to('um/s').value`)
        f_lambda_con = 0
        # I am using a < comparison here to account for the possibility that the given
        # wavelength is not EXACTLY 1520 AA or 2310 AA
        if (wavelength < 2000): 
            f_lambda_con = 1.40 * 10**(-15)
        else:
            f_lambda_con = 2.06 * 10**(-16)
        conversion_factor = ((10**23) * f_lambda_con * wavelength**2) / (constants.c.to('angstrom/s').value)
        #print("lambda^2/c = " + `(wavelength**2) / (constants.c.to('angstrom/s').value)`)

    elif (instrument == '2MASS'):
        #print("MAGZP: " + `header['MAGZP']`)
        fvega = 0
        if (header['FILTER'] == 'j'):
            fvega = 1594
        elif (header['FILTER'] == 'h'):
            fvega = 1024
        elif (header['FILTER'] == 'k'):
            fvega = 666.7
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
        pixelscale = u.deg.to(u.arcsec, header['CDELT2'])
        wavelength = header['WAVELENG']
        if (wavelength == 250):
            conversion_factor = (pixelscale**2) / 423
        elif (wavelength == 350):
            conversion_factor = (pixelscale**2) / 751
        elif (wavelength == 500):
            conversion_factor = (pixelscale**2) / 1587
    
    return conversion_factor

# Function: get_wavelength(header)
# A function to allow wavelength values to be obtained from a number of different
# header keywords
def get_wavelength(header):
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
        wavelength_units = 'micron'

    return wavelength, wavelength_units

ncols_input = ""
nlines_input = ""
image_input = ""

# Function: parse_command_line()
# This function parses the command line to obtain parameters.
# The parameters are checked for correctness and then returned to the calling function.
def parse_command_line():
    global phys_size
    global directory
    global conversion_factors

    try:
        opts, args = getopt.getopt(sys.argv[1:], "", ["directory=", "angular_physical_size=", "conversion_factors"])
    except getopt.GetoptError:
        print("An error occurred. Check your parameters and try again.")
        sys.exit(2)
    for opt, arg in opts:
        if opt in ("--angular_physical_size"):
            phys_size = float(arg)
        if opt in ("--directory"):
            directory = arg
        if opt in ("--conversion_factors"):
            conversion_factors = True

    # Now make sure that the values we have just grabbed from the command line are 
    # valid.
    # The angular physical size should be a number
    if (not is_number(phys_size)):
        print_usage()
        print("Error: angular physical size must be a number.")
        sys.exit()

    # And the directory should actually exist
    if (not os.path.isdir(directory)):
        print_usage()
        print("Error: The specifiied directory cannot be found.")
        sys.exit()

    return phys_size, directory, conversion_factors

# Function: output_conversion_factors(images_with_headers)
# Prints a formatted list of instruments, wavelengths, and conversion factors to
# Jy/pixel
# NOTETOSELF: maybe we can add a separator parameter - e.g. if the user wants the
# values to be comma-separated.
def output_conversion_factors(images_with_headers):
    print("Instrument\tWavelength\tConversion factor (to Jy/pixel)")
    for i in range(0, len(images_with_headers)):
        wavelength = images_with_headers[i][1]['WAVELENG']
        wavelength_units = images_with_headers[i][1].comments['WAVELENG']
        #print("Wavelength: " + `wavelength` + ' ' + `wavelength_units` + "; Sample image value: " + `images_with_headers[i][0][30][30]`)
        #print("Wavelength units: " + `wavelength_units`)
        #wavelength_microns = wavelength_to_microns(wavelength, wavelength_units)
        #print("Wavelengths in microns: " + `wavelength_microns`)
        
        instrument = get_instrument(images_with_headers[i][1])
        #print("Instrument: " + instrument)
        #print("Filename: " + images_with_headers[i][2])
    
        conversion_factor = get_conversion_factor(images_with_headers[i][1], instrument)
        print(instrument + '\t' + `wavelength` + '\t' + `conversion_factor`)
        #print

# Function: convert_images(images_with_headers)
# Converts all of the input images' native "flux units" to Jy/pixel
# The converted values are stored in the list of arrays, converted_data, and they
# are also saved as new FITS images.
def convert_images(images_with_headers):
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
        hdu = fits.PrimaryHDU(converted_data_array, images_with_headers[i][1])
        print("Creating " + converted_filename)
        hdu.writeto(converted_filename, clobber=True)

# Function: register_images(images_with_headers)
def register_images(images_with_headers):
    print("Registering images")

# Function: convolve_images(images_with_headers)
def convolve_images(images_with_headers):
    print("Convolving images")

# Function: resample_images(images_with_headers)
def resample_images(images_with_headers):
    print("Resampling images")

# Function: output_seds(images_with_headers)
def output_seds(images_with_headers):
    print("Outputting SEDs")

# Read the input image data and header into an NDData object
#hdulist = fits.open(image_input)
#d1 = NDData(hdulist[0].data, meta=hdulist[0].header)
#hdulist.close()

#print("Sample header value: " + d1.meta['OBJECT'])
#lngref_input = d1.meta['CRVAL1']
#latref_input = d1.meta['CRVAL2']
#xmag_input = d1.meta['CDELT1']
#ymag_input = d1.meta['CDELT2']

#print("lngref: " + `lngref_input`)
#print("latref: " + `latref_input`)
#print("xmag: " + `xmag_input` + "; converted: " + `u.deg.to(u.arcsec, xmag_input)`)
#print("ymag: " + `ymag_input` + "; converted: " + `u.deg.to(u.arcsec, ymag_input)`)
#xmag_input = u.deg.to(u.arcsec, xmag_input)
#ymag_input = u.deg.to(u.arcsec, ymag_input)
#print("xmag: " + `xmag_input`)

if __name__ == '__main__':
    phys_size = ''
    directory = ''
    conversion_factors = False
    phys_size, directory, conversion_factors = parse_command_line()

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

    if (conversion_factors):
        output_conversion_factors(images_with_headers)

    convert_images(images_with_headers)

    register_images(images_with_headers)

    convolve_images(images_with_headers)

    resample_images(images_with_headers)

    output_seds(images_with_headers)

    sys.exit()

# NOTETOSELF: the registration part has been updated in another txt file. Make sure to
# check that file (about physical size) before doing any more work on this code.

#First we create an artificial fits image
# unlearn some iraf tasks

iraf.unlearn('mkpattern')
#create a fake image "apixelgrid.fits", to which we will register all fits images

artdata.mkpattern(input="apixelgrid.fits", output="apixelgrid.fits", pattern="constant", pixtype="double", ndim=2, ncols=ncols_input, nlines=nlines_input)
#note that in the exact above line, the "ncols" and "nlines" should be wisely chosen, depending on the input images - they provide the pixel-grid 
#for each input fits image, we will create the corresponding artificial one - therefore we can tune these values such that we cover, for instance, XXarcsecs of the target - so the best is that user provides us with such a value

#Then, we tag the desired WCS in this fake image:
# unlearn some iraf tasks

iraf.unlearn('ccsetwcs')
#tag the desired WCS in the fake image "apixel.fits"

iraf.ccsetwcs(images="apixelgrid.fits", database="", solution="", xref=ncols_input/2.0, yref=nlines_input/2.0, xmag=xmag_input, ymag=ymag_input, xrotati=0.,yrotati=0.,lngref=lngref_input, latref=latref_input, lngunit="degrees", latunit="degrees", transpo="no", project="tan", coosyst="j2000", update="yes", pixsyst="logical", verbose="yes")
#note that the "xref" and "yref" are actually half the above "ncols", "nlines", respectively, so that we center each image
#note also that "xmag" and "ymag" is the pixel-scale, which in the current step ought to be the same as the native pixel-scale of the input image, for each input image - so we check the corresponding header value in each image
#note that "lngref" and "latref" can be grabbed by the fits header, it is actually the center of the target (e.g. ngc1569)
#note that we should make sure that the coordinate system is in coosyst="j2000" by checking the header info, otherwise we need to adjust that
# As of 2013-07-02, xmag, yman, lngref, and latref are all being obtained from the
# header of the input image

# Then, register the fits file of interest to the WCS of the fake fits file
# unlearn some iraf tasks

iraf.unlearn('wregister')
#register the sciense fits image

iraf.wregister(input=image_input, reference="apixelgrid.fits", output="scitestout.fits", fluxconserve="no")


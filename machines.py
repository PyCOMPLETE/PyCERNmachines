from __future__ import division

import numpy as np
from scipy.constants import c, e, m_p

from PyHEADTAIL.general.element import Element
import PyHEADTAIL.particles.generators as gen
from PyHEADTAIL.trackers.transverse_tracking import TransverseMap
from PyHEADTAIL.trackers.detuners import Chromaticity, AmplitudeDetuning
from PyHEADTAIL.trackers.simple_long_tracking import LinearMap, RFSystems


class Synchrotron(Element):

    def __init__(self, *args, **kwargs):
        '''
        Currently (because the RFSystems tracking uses a verlet integrator)
        the RFSystems element will be installed at s=circumference/2,
        which is correct for the smooth approximation
        '''
        for attr in kwargs.keys():
            if kwargs[attr] is not None:
                print 'Synchrotron init. From kwargs: %s = %s'%(attr, repr(kwargs[attr]))
                setattr(self, attr, kwargs[attr])

        self.create_transverse_map()
        self.create_longitudinal_map()

        # create the one_turn map: install the longitudinal map at
        # s = circumference/2
        self.one_turn_map = []
        for m in self.transverse_map:
            self.one_turn_map.append(m)

        # compute the index of the element before which to insert
        # the longitudinal map
        if (len(self.one_turn_map) % 2 == 0):
            insert_before = len(self.one_turn_map) // 2
        else:
            insert_before = len(self.one_turn_map) // 2 + 1
        print insert_before
        print self.one_turn_map
        self.one_turn_map.insert(insert_before, self.longitudinal_map)
        print self.one_turn_map

    def install_after_each_transverse_segment(self, element_to_add):
        '''Attention: Do not add any elements which update the dispersion!'''
        one_turn_map_new = []
        for element in self.one_turn_map:
            one_turn_map_new.append(element)
            if element in self.transverse_map:
                one_turn_map_new.append(element_to_add)
        self.one_turn_map = one_turn_map_new

    @property
    def gamma(self):
        return self._gamma
    @gamma.setter
    def gamma(self, value):
        self._gamma = value
        self._beta = np.sqrt(1 - self.gamma**-2)
        self._betagamma = np.sqrt(self.gamma**2 - 1)
        self._p0 = self.betagamma * m_p * c

    @property
    def beta(self):
        return self._beta
    @beta.setter
    def beta(self, value):
        self.gamma = 1. / np.sqrt(1-value**2)

    @property
    def betagamma(self):
        return self._betagamma
    @betagamma.setter
    def betagamma(self, value):
        self.gamma = np.sqrt(value**2 + 1)

    @property
    def p0(self):
        return self._p0
    @p0.setter
    def p0(self, value):
        self.gamma = value / (m_p * self.beta * c)

    @property
    def eta(self):
        return self.alpha - self.gamma**-2

    @property
    def Q_s(self):
        if self.p_increment!=0 or self.dphi1!=0:
            raise ValueError('Formula not valid in this case!!!!')
        return np.sqrt( e*np.abs(self.eta)*(self.h1*self.V1 + self.h2*self.V2)
                        / (2*np.pi*self.p0*self.beta*c) )

    @property
    def beta_z(self):
        return np.abs(self.eta)*self.circumference/2./np.pi/self.Q_s

    @property
    def R(self):
        return self.circumference/(2*np.pi)

    def track(self, bunch, verbose = False):
        for m in self.one_turn_map:
            if verbose:
                print 'Tracking through:'
                print m
            m.track(bunch)

    def create_transverse_map(self):

        chromaticity = Chromaticity(self.Qp_x, self.Qp_y)
        amplitude_detuning = AmplitudeDetuning(self.app_x, self.app_y, self.app_xy)

        self.transverse_map = TransverseMap(
            self.circumference, self.s,
            self.alpha_x, self.beta_x, self.D_x,
            self.alpha_y, self.beta_y, self.D_y,
            self.Q_x, self.Q_y,
            chromaticity, amplitude_detuning)

    def create_longitudinal_map(self):

        if self.longitudinal_focusing == 'linear':
            self.longitudinal_map = LinearMap([self.alpha], self.circumference,
                    self.Q_s, D_x=self.D_x[0], D_y=self.D_y[0])
        elif self.longitudinal_focusing == 'non-linear':
            self.longitudinal_map = RFSystems(self.circumference, [self.h1, self.h2], [self.V1, self.V2], [self.dphi1, self.dphi2],
                                        [self.alpha], self.gamma, self.p_increment,
                                        D_x=self.D_x[0], D_y=self.D_y[0])
        else:
            raise ValueError('ERROR: unknown focusing', self.longitudinal_focusing)

    def generate_6D_Gaussian_bunch(self, n_macroparticles, intensity, epsn_x, epsn_y, sigma_z):
        '''
        Generates a 6D Gaussian distribution of particles which is transversely
        matched to the Synchrotron. Longitudinally, the distribution is matched
        only in terms of linear focusing. For a non-linear bucket, the Gaussian
        distribution is cut along the separatrix (with some margin) and will
        gradually filament into the bucket. This will change the specified bunch
        length.
        '''
        if self.longitudinal_focusing == 'linear':
            check_inside_bucket = lambda z,dp : np.array(len(z)*[True])
        elif self.longitudinal_focusing == 'non-linear':
            check_inside_bucket = self.longitudinal_map.get_bucket(gamma=self.gamma).make_is_accepted(margin = 0.05)
        else:
            raise ValueError('Longitudinal_focusing not recognized!!!')

        beta_z    = np.abs(self.eta)*self.circumference/2./np.pi/self.Q_s
        sigma_dp  = sigma_z/beta_z
        epsx_geo = epsn_x/self.betagamma
        epsy_geo = epsn_y/self.betagamma

        bunch = gen.ParticleGenerator(macroparticlenumber=n_macroparticles,
                intensity=intensity, charge=self.charge, mass=self.mass,
                circumference=self.circumference, gamma=self.gamma,
                distribution_x=gen.gaussian2D(epsx_geo),
                distribution_y=gen.gaussian2D(epsy_geo),
                distribution_z=gen.cut_distribution(
                    gen.gaussian2D_asymmetrical(sigma_u=sigma_z, sigma_up=sigma_dp),
                    is_accepted=check_inside_bucket),
                linear_matcher_x=gen.transverse_linear_matcher(
                    alpha=self.alpha_x[0], beta=self.beta_x[0], dispersion=self.D_x[0]),
                linear_matcher_y=gen.transverse_linear_matcher(
                    alpha=self.alpha_y[0], beta=self.beta_y[0], dispersion=self.D_y[0])
                ).generate()

        return bunch

    def generate_6D_Gaussian_bunch_matched(self, n_macroparticles, intensity, epsn_x, epsn_y, sigma_z=None, epsn_z=None):
        '''
        Generates a 6D Gaussian distribution of particles which is transversely
        as well as longitudinally matched. The distribution is found iteratively
        to exactly yield the given bunch length while at the same time being
        stationary in the non-linear bucket. Thus, the bunch length should amount
        to the one specificed and should not change significantly during the
        Synchrotron motion.
        '''
        epsx_geo = epsn_x/self.betagamma
        epsy_geo = epsn_y/self.betagamma

        bunch = gen.ParticleGenerator(macroparticlenumber=n_macroparticles,
                intensity=intensity, charge=self.charge, mass=self.mass,
                circumference=self.circumference, gamma=self.gamma,
                distribution_x=gen.gaussian2D(epsx_geo),
                distribution_y=gen.gaussian2D(epsy_geo),
                distribution_z=gen.RF_bucket_distribution(
                    rfbucket=self.longitudinal_map.get_bucket(gamma=self.gamma),
                    sigma_z=sigma_z, epsn_z=epsn_z),
                linear_matcher_x=gen.transverse_linear_matcher(
                    alpha=self.alpha_x[0], beta=self.beta_x[0], dispersion=self.D_x[0]),
                linear_matcher_y=gen.transverse_linear_matcher(
                    alpha=self.alpha_y[0], beta=self.beta_y[0], dispersion=self.D_y[0])
                ).generate()

        return bunch

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from numpy.polynomial import polynomial as P

# H7 Intensity Data
df_H7 = pd.read_csv(r'results\Rubrene-H7-Intensity-Scan_20260730_165211\analysis\harmonic_analysis_20260730_171215\figures\power_mw_sample_327.csv')
df_H7.head()
input_power_mw_H7 = df_H7['power_mw']
signal_intensity_H7 = df_H7['background_corrected_integral']


focus_FWHM = 200e-6
spot_area = np.pi * (focus_FWHM / 2)**2

intensity_Wcm2_H7 = input_power_mw_H7 * 1000 / spot_area * 1e-12
x_H7 = np.log10(intensity_Wcm2_H7)
y_H7 = np.log10(signal_intensity_H7)

# Linear fit in log-log space
m_H7, b_H7 = np.polyfit(x_H7[1:-1], y_H7[1:-1], 1)
# create fit line for plotting
x_fit_H7 = np.linspace(x_H7.min(), x_H7.max(), 100)
y_fit_H7 = m_H7 * x_fit_H7 + b_H7

# H5
# H5 Intensity Data
df_H5 = pd.read_csv(r'results\Rubrene-H5-Intensity-Scan_20260730_150155\analysis\harmonic_analysis_20260730_153023\figures\power_mw_sample_327.csv')
df_H5.head()
input_power_mw_H5 = df_H5['power_mw']
signal_intensity_H5 = df_H5['background_corrected_integral']


focus_FWHM = 200e-6
spot_area = np.pi * (focus_FWHM / 2)**2

intensity_Wcm2_H5 = input_power_mw_H5 * 1000 / spot_area * 1e-12
x_H5 = np.log10(intensity_Wcm2_H5)
y_H5 = np.log10(signal_intensity_H5)

# Linear fit in log-log space
m_H5, b_H5 = np.polyfit(x_H5[1:-1], y_H5[1:-1], 1)
# create fit line for plotting
x_fit_H5 = np.linspace(x_H5.min(), x_H5.max(), 100)
y_fit_H5 = m_H5 * x_fit_H5 + b_H5

plt.plot(x_H7, y_H7, marker='o', linestyle='', label='H7', color='tab:purple')
plt.plot(x_fit_H7, y_fit_H7, label=f'H7 fit: slope={m_H7:.2f}', color='tab:purple')
plt.plot(x_H5, y_H5, marker='o', linestyle='', label='H5', color='tab:green')
plt.plot(x_fit_H5, y_fit_H5, label=f'H5 fit: slope={m_H5:.2f}', color='tab:green')
# plt.plot(intensity_Wcm2_H7, signal_intensity_H7, marker='o', linestyle='', label='Data')

# # Fit exponential model
# from scipy.optimize import curve_fit

# def exponential_model(x, a, b):
#     return a * np.exp(b * x)

# popt, _ = curve_fit(exponential_model, intensity_Wcm2_H7, signal_intensity_H7)
# x_fit = np.linspace(intensity_Wcm2_H7.min(), intensity_Wcm2_H7.max(), 100)
# y_fit = exponential_model(x_fit, *popt)
# plt.plot(x_fit, y_fit, 'r--', label=f'Exponential fit: {popt[0]:.2e}*exp({popt[1]:.2e}*x)')
# plt.yscale('log')
plt.xlabel('Log Driving Intensity (TW/cm²)')
plt.ylabel('Log Signal Intensity')
plt.title('H7 + H5 Intensity Data')
plt.legend(frameon=False)
plt.show()
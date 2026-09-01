from setuptools import find_packages, setup

setup(
    name="marina_custom_apps",
    version="0.42.1",
    description="Marina Trading Company custom Frappe/ERPNext modules",
    author="Marina Trading Company",
    author_email="it@marinafashion.com.sa",
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
)

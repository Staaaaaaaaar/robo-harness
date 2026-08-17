from setuptools import find_packages, setup

package_name = "rh_ros"

setup(
    name=package_name,
    version="0.0.0",
    packages=find_packages(exclude=("test",)),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
    ],
    package_data={package_name: ["py.typed"]},
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Staaaaaaaaar",
    maintainer_email="2300012435@stu.pku.edu.cn",
    description="Reusable ROS 2 runtime protocol helpers for RoboHarness.",
    license="NOASSERTION",
    tests_require=["pytest"],
)

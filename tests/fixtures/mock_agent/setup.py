from setuptools import find_packages, setup

package_name = "rh_mock_agent"

setup(
    name=package_name,
    version="0.0.0",
    packages=find_packages(exclude=("test",)),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Staaaaaaaaar",
    maintainer_email="2300012435@stu.pku.edu.cn",
    description="Deterministic CPU-only Agent contract fixture for RoboHarness.",
    license="NOASSERTION",
    tests_require=["pytest"],
    entry_points={"console_scripts": ["mock_agent = rh_mock_agent.node:main"]},
)

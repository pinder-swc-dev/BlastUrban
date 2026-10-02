FROM ubuntu:20.04 AS openfoam
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
  && apt-get install -y wget software-properties-common \
  && sh -c "wget -O - https://dl.openfoam.org/gpg.key | apt-key add -" \
  && add-apt-repository http://dl.openfoam.org/ubuntu \
  && apt-get update
RUN apt-get -y install openfoam9

FROM ubuntu:20.04 as prod
SHELL [ "/bin/bash", "-c" ]
ARG DEBIAN_FRONTEND=noninteractive
COPY --from=openfoam /opt/openfoam9 /opt/openfoam9
COPY blastfoam_*.deb .
RUN apt-get -qq -o=Dpkg::Use-Pty=0 update \
  && apt-get -qq -o=Dpkg::Use-Pty=0 install -y \
    gnuplot libopenmpi-dev python3 python3-vtk7 \
  && rm -rf /var/lib/apt/lists/*
RUN dpkg -i blastfoam_*.deb
RUN bash -lc 'set +e; source /opt/openfoam9/etc/bashrc; source /opt/blastfoam/etc/bashrc; set -e; \
    for utility in blastToVTK calculateImpulse; do \
        if ! command -v "$utility" >/dev/null 2>&1; then \
            wmake "/opt/blastfoam/applications/utilities/$utility"; \
            wclean "/opt/blastfoam/applications/utilities/$utility"; \
        fi; \
        command -v "$utility" >/dev/null; \
    done'
RUN echo "source /opt/openfoam9/etc/bashrc" >> ~/.bashrc \
  && echo "source /opt/blastfoam/etc/bashrc" >> ~/.bashrc \
  && source ~/.bashrc
WORKDIR /app/blastfoam
ENTRYPOINT ["/bin/bash", "-ci"]

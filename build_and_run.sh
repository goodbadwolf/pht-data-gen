#!/bin/bash

build() {
    cd ospray-studio/build || return 1
    if ! make -j ospStudio; then
        return 1
    fi
    cd ../..
    return 0
}

run() {
    local mode=$1
    local scene=$2
    local spp=$3

    OSP_OPTIONS="${mode}"

    if [ "$mode" = "batch" ]; then
        OSP_OPTIONS+=" --resolution 1024x1024"
    else
        OSP_OPTIONS+=" --resolution 1920x1080"
    fi

    OSP_OPTIONS+=" --renderer pathtracer"

    if [ "$mode" = "batch" ]; then
        OSP_OPTIONS+=" --spp ${spp}"
    fi

    OSP_OPTIONS+=" --pixelfilter 0"

    OSP_OPTIONS+=" --image ${scene}_${spp}spp"
    OSP_OPTIONS+=" --saveAlbedo"
    OSP_OPTIONS+=" --saveDepth"
    OSP_OPTIONS+=" --saveNormal"
    #OSP_OPTIONS+=" --saveLayers"
    OSP_OPTIONS+=" --format png"

    echo "Using options ${OSP_OPTIONS}"

    OSP_STUDIO_BASE="./ospray-studio/build/ospStudio"
    OSP_STUDIO_BASE+=" ${OSP_OPTIONS}"

    if [ "$scene" = "none" ]; then
        echo "Running ospStudio without any file"
        ${OSP_STUDIO_BASE}
    else
        scene_file="ospStudio-scenes/${scene}.sg"
        if [ -f "$scene_file" ]; then
            echo "Running ospStudio with ${scene}.sg"
            ${OSP_STUDIO_BASE} "$scene_file"
        else
            echo "Error: ${scene_file} not found"
            return 1
        fi
    fi

    if [ "$mode" = "gui" ] && [ "$scene" != "none" ]; then
        if [ -f "studio_scene.sg" ]; then
            echo "Updating ${scene}.sg"
            mv studio_scene.sg "ospStudio-scenes/${scene}.sg"
        fi
    fi
}

ALLOWED_SCENES="wavelet teapot_cloud multi none"
ALLOWED_SCENES_STR="${ALLOWED_SCENES// /, }"

ALLOWED_MODES="gui batch pht"
ALLOWED_MODES_STR="${ALLOWED_MODES// /, }"

main() {
    if [ $# -lt 2 ]; then
        echo "Usage: $0 <mode> <scene>"
        echo "  mode: $ALLOWED_MODES_STR"
        echo "  scene: $ALLOWED_SCENES_STR"
        echo "  spp: samples per pixel. Default 1"
        exit 1
    fi

    local mode=$1
    local scene=$2
    local spp=$3

    if [[ ! " $ALLOWED_MODES " =~ $mode ]]; then
        echo "Error: mode must be one of : $ALLOWED_MODES_STR"
        exit 1
    fi

    if [[ ! " $ALLOWED_SCENES " =~ $scene ]]; then
        echo "Error: scene must be one of: $ALLOWED_SCENES_STR"
        exit 1
    fi

    if [ -z "$spp" ] || [ "$spp" -eq 0 ] 2>/dev/null; then
        spp=1
    fi

    if build; then
        run "$mode" "$scene" "$spp"
    else
        echo "Build failed"
        exit 1
    fi
}

main "$@"

#!/bin/bash

build() {
    cd ospray-studio/build || return 1
    if ! make -j ospStudio; then
        return 1
    fi
    cd ../..
    return 0
}

mode="pht"
scene="wavelet"
spp="4"
dev_mode=false

run() {
    OSP_OPTIONS="${mode}"

    if [ "$dev_mode" = true ]; then
        OSP_OPTIONS+=" --resolution 256x256"
    else
        OSP_OPTIONS+=" --resolution 1024x1024"
    fi

    OSP_OPTIONS+=" --renderer pathtracer"

    if [ "$mode" = "pht" ]; then
        OSP_OPTIONS+=" --spp ${spp}"
    fi

    OSP_OPTIONS+=" --pixelfilter 0"
    OSP_OPTIONS+=" --image ${scene}_${spp}spp"
    OSP_OPTIONS+=" --saveAlbedo"
    OSP_OPTIONS+=" --saveDepth"
    OSP_OPTIONS+=" --saveNormal"
    OSP_OPTIONS+=" --format png"

    if [ "$mode" = "pht" ]; then
        OSP_OPTIONS+=" --cameraGenerator fibonacci"
        OSP_OPTIONS+=" --cameraGeneratorFlipYZ"
        OSP_OPTIONS+=" --numFrames 100"
        OSP_OPTIONS+=" --forceOverwrite"
        OSP_OPTIONS+=" --jitter 0"
        OSP_OPTIONS+=" --zoom 0"
        OSP_OPTIONS+=" --outputPath images/${scene}_${spp}spp"
    fi

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
            echo "Error: Scene at path ${scene_file} not found"
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

usage() {
    echo "Usage: $0 -m|--mode <mode> -s|--scene <scene> [-p|--spp <spp>] [-d|--dev-mode]"
    echo "  -m, --mode      Mode: gui or pht (required)"
    echo "  -s, --scene     Scene name (required)"
    echo "  -p, --spp       Samples per pixel (optional, default: 1)"
    echo "  -d, --dev-mode  Enable development mode (optional flag)"
    exit 1
}

main() {
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
        -m | --mode)
            mode="$2"
            shift 2
            ;;
        -s | --scene)
            scene="$2"
            shift 2
            ;;
        -p | --spp)
            spp="$2"
            shift 2
            ;;
        -d | --dev-mode)
            dev_mode=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
        esac
    done

    # mode must be one of: gui, pht
    if [ "$mode" != "gui" ] && [ "$mode" != "pht" ]; then
        echo "Error: mode must be one of : gui, pht"
        exit 1
    fi

    if [ -z "$spp" ] || [ "$spp" -eq 0 ] 2>/dev/null; then
        spp=1
    fi

    if build; then
        run
    else
        echo "Build failed"
        exit 1
    fi
}

main "$@"

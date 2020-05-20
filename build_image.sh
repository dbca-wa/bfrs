#!/bin/bash

action="$1"
env="$2"
debug="False"

if [[ "$env" = "prod" ]]; then
    tag="$3"
	if [[ "$tag" = "" ]]; then
		echo "Version tag is missing"
    	exit 1
	fi
    disttype="release"
    debug="False"
elif [[ "$env" = "uat" ]]; then
	tag="latest"
    disttype="dev"
    debug="True"
elif [[ "$env" = "dev" ]]; then
	tag="dev"
    disttype="dev"
    debug="True"
elif [[ "$env" = "" ]]; then
    echo "Please choose the environment where the image will be running? release , uat or dev"
    exit 1
else
    echo "Only release, uat and dev environment are supported."
    exit 1
fi

echo "Begin to build bfrs with tag '${tag}' for '$env' environment"


if [[ "$action" = "all" ]] || [[ "$action" = "build"  ]]; then
  	docker image build -t dbcawa/bfrs:${tag} -f Dockerfile .
    if [[ $? -ne 0 ]]; then
    	echo "Build docker image failed"
    	exit 1
    fi
fi

if [[ "$action" = "all_ignore" ]] || [[ "$action" = "test_ignore"  ]]; then
    docker container run --publish 30019:8080 --env DEBUG=debug --env ENV_TYPE=${env} --env DIST_TYPE=${disttype} dbcawa/bfrs:${tag}
    if [[ $? -ne 0 ]]; then
    	echo "Run the image in local container failed"
    	exit 1
    fi
    echo "Image is running in local container which is listening on 30019 port, please test it..."

    if [[ "$action" = "all" ]] ; then
        printf "Test successfully, (Y)es  (N)o  (Y):"
        read isOk
        isOk="${isOk^^}"
        if [[ "$isOk" != "Y" ]] && [[ "$isOk" != "" ]] ; then
        	echo "Test failed."
        	exit 1
        fi
    fi
fi

if [[ "$action" = "all" ]] || [[ "$action" = "push"  ]]; then
    pass show docker-credential-helpers/docker-pass-initialized-check
    docker login
    
    docker image push dbcawa/bfrs:${tag}
    if [[ $? -ne 0 ]]; then
    	echo "Failed to push imgage to docker hub"
    	exit 1
    fi
    echo "Succeed to publish imgage to docker hub"
    echo "Please logon to the docker runtime server to run the image "
fi

